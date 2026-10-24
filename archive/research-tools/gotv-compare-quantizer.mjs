import fs from 'node:fs';
import {getQuantalizedFloat} from '../../gotv-parser-audit/src/parser/entities/quantizedFloat.ts';
const rows=JSON.parse(fs.readFileSync('.agent-tmp/gotv-research-plan/quantizer-native-init.json','utf8'));
for(const r of rows){r.prototype=getQuantalizedFloat(r.bits,r.flags,r.low,r.high);r.same=r.prototype.no_scale===r.raw&&r.prototype.bit_count===r.effective_bits&&(r.raw||(Math.fround(r.prototype.low)===r.configured_low&&Math.fround(r.prototype.high)===r.configured_high&&r.prototype.flags===r.effective_flags));}
fs.writeFileSync('.agent-tmp/gotv-research-plan/quantizer-init-comparison.json',JSON.stringify(rows,null,2)+'\n');console.log(JSON.stringify(rows.filter(r=>!r.same),null,2));
