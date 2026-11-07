from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ops.cloud.prepare_financial_reports import publish_image

class RenderHeightTests(unittest.TestCase):
    def test_measure_fonts_before_screenshot_and_refuse_unknown_height(self):
        with tempfile.TemporaryDirectory() as tmp:
            page=Path(tmp)/'report.html';page.write_text('<main class="page">日报</main></body>');png=Path(tmp)/'report.png'
            with patch('ops.cloud.prepare_financial_reports.require_cjk_font'),patch('ops.cloud.prepare_financial_reports.chrome_owned',return_value='<html data-render-height="1732">') as chrome:
                publish_image(page,png,upload=False)
                self.assertIn('--window-size=1200,1732',chrome.call_args.args[0]);self.assertEqual(chrome.call_count,2)
            with patch('ops.cloud.prepare_financial_reports.require_cjk_font'),patch('ops.cloud.prepare_financial_reports.chrome_owned',return_value='<html>') as chrome:
                with self.assertRaises(RuntimeError):publish_image(page,png,upload=False)
                self.assertEqual(chrome.call_count,1)
