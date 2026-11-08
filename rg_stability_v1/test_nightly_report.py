from pathlib import Path
import tempfile,json,unittest
from rg_nightly_report import build_report

class NightlyReportTest(unittest.TestCase):
    def test_read_only_queue_report(self):
        with tempfile.TemporaryDirectory() as d:
            app=Path(d)
            queue=app/'queue.json'
            queue.write_text(json.dumps({'running':True,'rows':[{'stream':'885','status':'RUNNING','stage':'MULTI_DIALOGUE'}]}))
            result=build_report(app,queue,streams=('885',))
            self.assertTrue(result['queue_running'])
            self.assertEqual(result['streams'][0]['stream'],'885')
            self.assertEqual(result['streams'][0]['release_status'],'REVIEW')
            self.assertEqual(result['totals']['unresolved'],1)
            self.assertFalse(result['live_workers_modified'])
if __name__=='__main__':unittest.main()
