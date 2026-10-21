import base64
import contextlib
import io
import imaplib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pm_scraper.actions_runner import key_bytes, seal, unseal, persist, execute, Gmail, safe_error
from pm_scraper.state import State


class ActionsRunnerTests(unittest.TestCase):
 def setUp(self):
  self.enterContext(contextlib.redirect_stdout(io.StringIO()))
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);self.data=self.root/'data';self.data.mkdir()
  State(self.data/'state.sqlite3').close()
  (self.data/'meta.json').write_text(json.dumps({'recipient':'test@example.org','attempts':{}}))
  self.key=os.urandom(32)
 def test_round_trip_and_tamper_rejection(self):
  encrypted=seal(self.data,self.key)
  self.assertNotIn(b'test@example.org',encrypted)
  out=self.root/'restored';unseal(encrypted,out,self.key)
  self.assertEqual((out/'state.sqlite3').read_bytes(),(self.data/'state.sqlite3').read_bytes())
  with self.assertRaises(Exception):unseal(encrypted[:-1]+bytes([encrypted[-1]^1]),self.root/'tampered',self.key)
 def test_invalid_key_rejected(self):
  with self.assertRaises(ValueError):key_bytes(base64.b64encode(b'bad').decode())
 def git(self,path,*args):
  return subprocess.check_output(['git','-C',str(path),*args],stderr=subprocess.PIPE,text=True).strip()
 def test_persistence_rejects_concurrent_writer(self):
  remote=self.root/'remote.git';subprocess.run(['git','init','--bare',str(remote)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  first=self.root/'first';self.git(self.root,'clone',str(remote),str(first))
  self.git(first,'checkout','-b','runtime-state');self.git(first,'config','user.name','test');self.git(first,'config','user.email','test@example.org')
  persist(self.data,first,self.key,'bootstrap')
  second=self.root/'second';self.git(self.root,'clone','--branch','runtime-state',str(remote),str(second))
  self.git(second,'config','user.name','test');self.git(second,'config','user.email','test@example.org')
  persist(self.data,first,self.key,'newer')
  with self.assertRaises(subprocess.CalledProcessError):persist(self.data,second,self.key,'stale')
 def run_fixture(self,send=False,attempt=None):
  if attempt:
   (self.data/'meta.json').write_text(json.dumps({'recipient':'test@example.org','attempts':{'123':attempt}}))
  checkout=self.root/'checkout';checkout.mkdir()
  encrypted=seal(self.data,self.key);(checkout/'state.enc').write_bytes(encrypted)
  source=self.root/'source';source.mkdir()
  (source/'run.py').write_text('''import sys,json
from pathlib import Path
out=Path(sys.argv[sys.argv.index('--output')+1]);out.mkdir()
(out/'email.json').write_text(json.dumps({'subject':"Tiny's Daily Job Report",'run_marker':'fixture','body_markdown':'No matches.\\n- Saving: not saved\\n- Run marker: fixture','delivery_status':'not_sent'}))
(out/'results.json').write_text(json.dumps({'fixture':True,'arguments':sys.argv}))
(out/'report.md').write_text('Current audit')
raise SystemExit(2)
''')
  return checkout,source,encrypted
 def test_validation_never_sends_or_persists(self):
  checkout,source,encrypted=self.run_fixture()
  environment={'STATE_ENCRYPTION_KEY':base64.b64encode(self.key).decode(),'GITHUB_RUN_ID':'123'}
  with patch.dict(os.environ,environment),patch('pm_scraper.actions_runner.git',return_value='abc'),patch('pm_scraper.actions_runner.persist') as save,patch.object(Gmail,'send') as send:
   code=execute(checkout,source,self.root/'output',False)
  self.assertEqual(code,0);save.assert_not_called();send.assert_not_called()
  self.assertEqual((checkout/'state.enc').read_bytes(),encrypted)
  restored=self.root/'validation';unseal((self.root/'output/validation.enc').read_bytes(),restored,self.key)
  draft=json.loads((restored/'email.json').read_text())
  self.assertEqual(draft['run_marker'],'tiny-actions-123')
  self.assertIn('production state unchanged',draft['body_markdown'])
 def test_delivery_checkpoints_before_send_and_saves_receipt(self):
  checkout,source,_=self.run_fixture()
  environment={'STATE_ENCRYPTION_KEY':base64.b64encode(self.key).decode(),'GITHUB_RUN_ID':'123','GMAIL_ADDRESS':'sender@example.org','GMAIL_APP_PASSWORD':'fixture-only'}
  events=[]
  with patch.dict(os.environ,environment),patch('pm_scraper.actions_runner.git',return_value='abc'),patch('pm_scraper.actions_runner.persist',side_effect=lambda *args:events.append(args[-1])),patch.object(Gmail,'find',return_value=[]),patch.object(Gmail,'send',side_effect=lambda *args:events.append('SMTP')):
   code=execute(checkout,source,self.root/'output',True)
  self.assertEqual(code,0)
  self.assertEqual(events,['Prepare tiny-actions-123','Record send intent tiny-actions-123','SMTP','Receipt tiny-actions-123'])
 def test_uncertain_send_never_automatically_repeats(self):
  checkout,source,_=self.run_fixture(attempt={'status':'sending'})
  environment={'STATE_ENCRYPTION_KEY':base64.b64encode(self.key).decode(),'GITHUB_RUN_ID':'123','GMAIL_ADDRESS':'sender@example.org','GMAIL_APP_PASSWORD':'fixture-only'}
  with patch.dict(os.environ,environment),patch.object(Gmail,'find',return_value=[]),patch.object(Gmail,'send') as send:
   with self.assertRaisesRegex(RuntimeError,'uncertain'):execute(checkout,source,self.root/'output',True)
   send.assert_not_called()
 def test_sent_message_is_reconciled_without_retrieval_or_resend(self):
  checkout,source,_=self.run_fixture(attempt={'status':'sending'})
  environment={'STATE_ENCRYPTION_KEY':base64.b64encode(self.key).decode(),'GITHUB_RUN_ID':'123','GMAIL_ADDRESS':'sender@example.org','GMAIL_APP_PASSWORD':'fixture-only'}
  with patch.dict(os.environ,environment),patch.object(Gmail,'find',return_value=['42']),patch('pm_scraper.actions_runner.persist'),patch.object(Gmail,'send') as send,patch('pm_scraper.actions_runner.subprocess.run') as retrieve:
   self.assertEqual(execute(checkout,source,self.root/'output',True),0)
   send.assert_not_called();retrieve.assert_not_called()

 def test_safe_authentication_diagnostic_does_not_disclose_server_details(self):
  diagnostic=safe_error(imaplib.IMAP4.error('[AUTHENTICATIONFAILED] Invalid credentials for private@example.org sensitive-value'))
  self.assertIn('rejected IMAP authentication',diagnostic)
  self.assertNotIn('private@example.org',diagnostic)
  self.assertNotIn('sensitive-value',diagnostic)
 def test_gmail_app_password_accepts_google_display_spacing(self):
  gmail=Gmail(' sender@example.org\n','abcd efgh ijkl mnop\n')
  self.assertEqual(gmail.address,'sender@example.org')
  self.assertEqual(gmail.password,'abcdefghijklmnop')

 def test_seven_day_runner_passes_override_without_changing_default(self):
  checkout,source,encrypted=self.run_fixture()
  environment={'STATE_ENCRYPTION_KEY':base64.b64encode(self.key).decode(),'GITHUB_RUN_ID':'123'}
  with patch.dict(os.environ,environment),patch('pm_scraper.actions_runner.git',return_value='abc'):
   self.assertEqual(execute(checkout,source,self.root/'output',False,7),0)
  restored=self.root/'validation';unseal((self.root/'output/validation.enc').read_bytes(),restored,self.key)
  args=json.loads((restored/'results.json').read_text())['arguments']
  self.assertEqual(args[args.index('--max-post-age-days')+1],'7')
  self.assertEqual(json.loads((restored/'meta.json').read_text())['attempts']['123']['freshness_days'],7)
  self.assertEqual(execute.__defaults__,(False,2))
  self.assertEqual((checkout/'state.enc').read_bytes(),encrypted)
