import unittest
from unittest.mock import patch
from pm_scraper.http import HttpClient, FetchError

class RobotsRulesTests(unittest.TestCase):
 def request(self,rules,url):
  client=HttpClient(delay=0,retries=0)
  with patch.object(client,'_request',side_effect=[(rules,'https://example.org/robots.txt',{}),('body',url,{})]) as read:
   result=client.text(url)
   self.assertEqual(read.call_count,2)
   return result
 def test_longer_allow_rule_overrides_blanket_disallow(self):
  rules='User-agent: *\nDisallow: /\nAllow: /api/apply\n'
  self.assertEqual(self.request(rules,'https://example.org/api/apply/v2/jobs'),'body')
 def test_blanket_disallow_still_blocks_float_style_feed(self):
  client=HttpClient(delay=0,retries=0)
  with patch.object(client,'_request',return_value=('User-agent: *\nDisallow: /','',{})) as read:
   with self.assertRaises(FetchError) as error:client.text('https://example.org/jobs.json')
   self.assertEqual(error.exception.kind,'robots_denied');self.assertEqual(read.call_count,1)
 def test_longer_disallow_wins_over_broad_allow(self):
  client=HttpClient(delay=0,retries=0)
  rules='User-agent: *\nAllow: /careers\nDisallow: /careers/private\n'
  with patch.object(client,'_request',return_value=(rules,'',{})):
   with self.assertRaises(FetchError):client.text('https://example.org/careers/private/jobs')
 def test_api_http_403_remains_a_block_even_when_robots_allows(self):
  client=HttpClient(delay=0,retries=0)
  with patch.object(client,'_request',side_effect=[('User-agent: *\nAllow: /','',{}),FetchError('HTTP 403','blocked')]):
   with self.assertRaises(FetchError) as error:client.text('https://example.org/api/jobs')
   self.assertEqual(error.exception.kind,'blocked')

 def test_explicit_refresh_does_not_reuse_a_cached_empty_page(self):
  client=HttpClient(delay=0,retries=0)
  url='https://example.org/jobs'
  with patch.object(client,'_request',side_effect=[('User-agent: *\nAllow: /','',{}),('empty',url,{}),('jobs',url,{})]) as read:
   self.assertEqual(client.text(url),'empty')
   self.assertEqual(client.text(url),'empty')
   self.assertEqual(client.text(url,refresh=True),'jobs')
   self.assertEqual(read.call_count,3)
