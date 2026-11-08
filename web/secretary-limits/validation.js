// Pure input feedback. The server remains the authority for numeric limits.
export const fields = [
  ['max_quantity', 'QMAX · 单笔股数（股）'],
  ['max_order_value', 'OMAX · 单笔金额（USD）'],
  ['max_risk_per_order', 'RMAX · 单笔风险（USD）'],
  ['max_symbol_exposure', 'SMAX · 单股持仓上限（USD）'],
  ['max_gross_exposure', 'GMAX · 账户总敞口（USD）'],
];

export function validateField(key, raw) {
  const quantity = key === 'max_quantity';
  const optional = ['max_symbol_exposure', 'max_gross_exposure'].includes(key);
  const value = typeof raw === 'string' ? raw.trim() : '';
  if (!value) return quantity ? '请填写单笔股数，当前仅支持整数股数。' : `请填写金额（USD）${optional ? '，或填写“不限”' : ''}。`;
  if (optional && value === '不限') return '';
  // Compare decimal digits directly: Number() can round 1.0000000000000001 to 1.
  const match = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(value);
  if (!match) return quantity ? '请输入有效数字，当前仅支持整数股数。' : '请输入有效数字，单位 USD；无需填写单位符号。';
  const fraction = match[3] ?? match[4] ?? '';
  const digits = ((match[2] || '') + fraction).replace(/^0+/, '');
  if (!digits) return '';
  if (match[1] === '-') return quantity ? '股数不能为负数，请输入 0 或正整数。' : '金额不能为负数，请输入 0 或正数（USD）。';
  const scale = fraction.length - Number(match[5] || 0);
  const magnitude = digits.length - scale;
  if (magnitude > 10 || (magnitude === 10 && (digits[0] !== '1' || /[1-9]/.test(digits.slice(1)))))
    return `数值不能超过 1,000,000,000${quantity ? ' 股' : ' USD'}。`;
  if (!Number.isFinite(scale)) return '数字格式超出支持范围，请使用普通数字。';
  if (quantity && scale > 0 && /[1-9]/.test(digits.slice(-scale)))
    return '当前仅支持整数股数，请输入 0 或正整数；暂不支持小数股。';
  return '';
}

export function validateFields(values) {
  const errors = {}, settings = {};
  for (const [key] of fields) {
    const text = typeof values[key] === 'string' ? values[key].trim() : '';
    const error = validateField(key, text);
    if (error) errors[key] = error;
    settings[key] = text === '不限' ? null : text;
  }
  return {errors, settings};
}
