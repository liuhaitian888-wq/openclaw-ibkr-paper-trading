"""Actual JS validation and server field errors; no production state or network."""
from contextlib import closing
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from reporting.agent_secretary import SecretaryArchive
from reporting.telegram_gate import DEFAULT


class SecretaryFieldFeedbackTests(unittest.TestCase):
    def test_javascript_decimal_quantity_and_five_field_errors(self):
        node=shutil.which('node') or '/Applications/Codex.app/Contents/Resources/cua_node/bin/node'
        if not Path(node).is_file():self.skipTest('Node runtime not available')
        source=Path(__file__).resolve().parents[1]/'web/secretary-limits/validation.js'
        script=r'''
            const assert = await import('node:assert/strict');
            const fs = await import('node:fs');
            const code = fs.readFileSync(process.argv[2], 'utf8');
            const {validateField, validateFields} = await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
            const good={max_quantity:'100',max_order_value:'20000',max_risk_per_order:'10.50',max_symbol_exposure:'不限',max_gross_exposure:'0'};
            assert.equal(Object.keys(validateFields(good).errors).length,0);
            for(const key of Object.keys(good)){
                for(const value of ['-1', 'NaN', 'Infinity', '1 USD', '1000000001']) assert.ok(validateField(key,value),key+': '+value);
                assert.equal(validateField(key,'0'),''); assert.equal(validateField(key,''),''); assert.equal(validateField(key,'不限'),'');
            }
            assert.match(validateField('max_quantity','1.5'),/整数股数/);
            assert.match(validateField('max_quantity','1.0000000000000001'),/整数股数/);
            assert.ok(validateField('max_order_value','1000000000.000000001'));
            assert.equal(validateField('max_quantity','1.00'),'');
            assert.equal(validateField('max_quantity','1e2'),'');
            for(const key of Object.keys(good).slice(1)) assert.equal(validateField(key,'0.25'),'');
            assert.equal(validateField('max_order_value','不限'),'');
            assert.equal(validateField('max_risk_per_order','不限'),'');
            const invalid=validateFields({...good,max_quantity:'1.5',max_order_value:'',max_symbol_exposure:'-2'});
            assert.deepEqual(Object.keys(invalid.errors),['max_quantity','max_symbol_exposure']);
            assert.equal(validateFields(good).settings.max_symbol_exposure,null);
        '''
        result=subprocess.run([node,'--input-type=module','-',str(source)],input=script,text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_server_collects_all_errors_without_cap_mutation(self):
        from reporting.telegram_gate import validate_form,GateValidationError
        with self.assertRaises(GateValidationError) as caught:
            validate_form({**DEFAULT,'max_quantity':'1.5','max_order_value':'','max_gross_exposure':-1})
        self.assertEqual(set(caught.exception.field_errors),{'max_quantity','max_gross_exposure'})
        self.assertIn('整数股数',caught.exception.field_errors['max_quantity'])
        result=validate_form({**DEFAULT,'max_order_value':'0.25'})
        self.assertEqual(result['max_order_value'],'0.25')
        for value in (float('nan'),float('inf'),True):
            with self.assertRaises(GateValidationError):validate_form({**DEFAULT,'max_quantity':value})
        with tempfile.TemporaryDirectory() as tmp:
            from reporting.gate_web import dispatch
            root=Path(tmp);archive=SecretaryArchive(root/'agent_secretary.sqlite3')
            cfg=dict(owner_user_id=123,owner_private_chat_id=123,owner_private_verified=True,bot_token='offline-placeholder')
            with patch('reporting.gate_web.verify_init_data',return_value=123):
                with self.assertRaises(GateValidationError):dispatch(archive,root,cfg,{'numeric_gate_controls_approved':True},'/api/preview',
                    dict(initData='offline',revision=0,settings={**DEFAULT,'max_quantity':'1.5'}))
            self.assertFalse((root/'runtime/risk-controls.json').exists())
            with closing(archive.connect()) as c:
                self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='secretary_gate_versions'").fetchone())
