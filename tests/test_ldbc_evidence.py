import unittest
from graph_mf.ldbc_evidence import schedule_audits, service_metrics


class EvidenceTests(unittest.TestCase):
    def test_warmup_pass_cannot_hide_measurement_failure(self):
        audit = schedule_audits('PASSED SCHEDULE AUDIT\nFAILED SCHEDULE AUDIT')
        self.assertFalse(audit['measurement_pass'])
        self.assertFalse(audit['all_phases_pass'])
        self.assertFalse(schedule_audits('Workload completed successfully')['measurement_pass'])
        self.assertTrue(schedule_audits('FAILED SCHEDULE AUDIT\nPASSED SCHEDULE AUDIT')['measurement_pass'])
        self.assertFalse(schedule_audits('PASSED SCHEDULE AUDIT',expected_phases=2)['measurement_pass'])
        self.assertTrue(schedule_audits('PASSED SCHEDULE AUDIT',expected_phases=1)['measurement_pass'])

    def test_service_weighting_and_coverage_are_actual(self):
        result = dict(unit='MILLISECONDS', total_count=11, total_duration=1000, throughput=11,
            all_metrics=[dict(name=name, count=count,
                run_time=dict(unit='MILLISECONDS', count=count, mean=mean, **{'95th_percentile':mean}))
                for name,count,mean in [('read',10,1),('update',1,20)]])
        measured = service_metrics(result)
        self.assertEqual(measured['cumulative_operation_ms'],30)
        self.assertEqual(measured['weighted_mean_ms'],30/11)
        self.assertEqual(measured['executed_types'],2)
        result['total_count']=12
        with self.assertRaises(ValueError):
            service_metrics(result)
