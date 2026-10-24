import unittest
from pm_scraper.filtering import Screener
from pm_scraper.daily import prepare_email
from test_screening import CFG, NOW, BASE, job


class PortugalEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.cfg={**CFG,'require_portugal_eligibility':True,'include_unknown_freshness':True,'include_future_dated':True}
        self.s=Screener(self.cfg)
        self.payload={'criteria':self.cfg,'started_at':NOW.isoformat(),'sources':[],
                      'coverage':{'sources':1,'complete':1,'attention':0}}

    def report(self,**values):
        j=job(**values);a=self.s.assess(j,NOW)
        return a,prepare_email([(j,a)],self.payload)

    def test_remote_label_and_portugal_boilerplate_do_not_override_foreign_location(self):
        for label,countries in [('Spain',[]),('Remote Germany',[]),('Remote US',[]),('Tokyo',[]),('', ['DE']),('Worldwide',['US'])]:
            with self.subTest(label=label):
                a,email=self.report(location=label,countries=countries)
                self.assertEqual(a.checks['portugal_eligibility']['status'],'fail')
                self.assertEqual(email['job_keys'],[])

    def test_missing_country_permission_is_withheld_even_with_fresh_or_unknown_date(self):
        for date,kind in [(None,'unknown'),('2026-10-20','original_posted'),('2026-10-18','original_posted')]:
            a,email=self.report(location='EMEA',countries=[],posted_at=date,date_kind=kind,description=BASE.replace('Fully remote within Portugal.','Fully remote.'))
            self.assertEqual(a.checks['portugal_eligibility']['status'],'unknown')
            self.assertEqual(email['job_keys'],[])

    def test_portugal_option_and_portuguese_remote_permission_are_allowed(self):
        for label,countries in [('Remote Portugal',[]),('Spain / Portugal',[]),('Europe',['ES','PT']),('Porto',['PT'])]:
            a,email=self.report(location=label,countries=countries)
            self.assertEqual(a.checks['portugal_eligibility']['status'],'pass')
            self.assertEqual(len(email['job_keys']),1)

    def test_foreign_residence_and_working_restrictions_override_portugal_label(self):
        for rule in ['You must be based in Spain.','This position is based in Germany.',
                     'Candidates should be located in Greece.',
                     'This role is only open to candidates based in Ireland.',
                     'You can only work remotely from Poland.']:
            with self.subTest(rule=rule):
                a,email=self.report(description=BASE+' '+rule)
                self.assertEqual(a.checks['residence']['status'],'fail')
                self.assertEqual(email['job_keys'],[])

    def test_required_question_is_unresolved_not_assumed_to_require_yes(self):
        a,email=self.report(metadata={'application_questions':[{'label':'Are you currently based in Spain?','required':True}]})
        self.assertEqual(a.checks['residence']['status'],'pass')
        self.assertEqual(a.checks['portugal_eligibility']['status'],'unknown')
        self.assertEqual(email['job_keys'],[])

    def test_sanctioned_territory_declaration_does_not_require_residing_there(self):
        question='Are you located in one of the following countries or regions: Belarus, Cuba, Iran, North Korea (DPRK), Syria, or Russia?'
        a,email=self.report(metadata={'application_questions':[{'label':question,'required':True}]})
        self.assertEqual(a.checks['portugal_eligibility']['status'],'pass')
        self.assertEqual(len(email['job_keys']),1)

    def test_application_description_explicit_foreign_requirement_is_rejected(self):
        a,email=self.report(metadata={'application_questions':[{'label':'Location','description':'You must reside in Germany.','required':True}]})
        self.assertEqual(a.checks['residence']['status'],'fail')
        self.assertEqual(email['job_keys'],[])

    def test_location_alternatives_and_optional_salary_mentions_remain_allowed(self):
        for rule in ['You must be based in Spain, Portugal or France.',
                     'You must reside in Porto or Braga.',
                     'If you are based in Poland, the salary range is 31,000-40,000 PLN.',
                     'Our offices are in Germany and Japan.',
                     'Relocation to Germany is optional.']:
            with self.subTest(rule=rule):
                a,email=self.report(description=BASE+' '+rule)
                self.assertNotEqual(a.status,'rejected')
                self.assertEqual(len(email['job_keys']),1)


if __name__=='__main__':
    unittest.main()
