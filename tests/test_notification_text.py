from datetime import datetime
import unittest
from reporting.notification_text import notification_text

class NotificationTextTests(unittest.TestCase):
 def item(self):
  return dict(id=805,incident_key='paper-safety:protection:NVDA',generation=1,
    kind='PROTECTION_PROTECTION_UNKNOWN',payload=dict(severity='RED',observed_at='2026-11-06T16:33:05.264880+00:00',
    reason='PROTECTION_UNKNOWN',scope='PAPER_SAFETY',symbol='NVDA',quantity=1.0,protection_status='PROTECTION_UNKNOWN',
    user_action='Review broker protection/session; replacement orders require explicit approval',queued_at=1793982785.264994))
 def test_blank_lines_human_types_seconds_advice_and_last_identity(self):
  text=notification_text(self.item(),1793982787.355406)
  self.assertIn('保护状态待核验\n\n',text);self.assertIn('2026-11-06 17:33:05',text)
  self.assertNotIn('.264880',text);self.assertNotIn('.355406',text)
  self.assertIn('数量：1\n\n',text);self.assertIn('建议你操作：',text)
  self.assertIn('故障批次：NVDA保护状态·第1次故障',text)
  self.assertTrue(text.endswith('事件编号：805'));self.assertNotIn('Telegram确认不等于',text)
 def test_caption_limit_retains_timing_and_final_identity(self):
  item=self.item();item['payload']['reason']='很长的实际报告'*1000
  text=notification_text(item,1793982787.355406,max_length=1024)
  self.assertLessEqual(len(text),1024);self.assertIn('排队时间（柏林）',text)
  self.assertTrue(text.endswith('事件编号：805'))
 def test_negative_delay_is_visible_and_unverified_timezone_is_explicit(self):
  item=self.item();item['payload'].update(scheduled_at=1000,observed_at='2026-11-06T16:33:05.264880')
  text=notification_text(item,999.75)
  self.assertIn('时区未核验',text);self.assertIn('相对计划延迟：-1 秒',text)
 def test_embedded_report_keeps_its_declared_timezone_and_raw_data_is_unchanged(self):
  item=self.item();original=item['payload']['observed_at']
  item['payload']['reason']='计划（Asia/Shanghai）：2026-11-06T09:00:00.123456+08:00'
  text=notification_text(item,1793982787.355406)
  self.assertIn('2026-11-06T09:00:00+08:00',text)
  self.assertEqual(item['payload']['observed_at'],original)
