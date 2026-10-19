from pathlib import Path
import struct,json,hashlib

def varint(b,p):
 v=0
 for i in range(10):
  x=b[p];p+=1;v|=(x&127)<<(i*7)
  if not x&128:return v,p
 raise ValueError('varint')
def fields(b,p=0,end=None):
 if end is None:end=len(b)
 result=[]
 while p<end:
  key,p=varint(b,p)
  if not key:return result,p-1
  number,kind=key>>3,key&7
  if kind==0:value,p=varint(b,p)
  elif kind==2:
   n,p=varint(b,p);value=b[p:p+n];p+=n
   if p>end:raise ValueError('length')
  elif kind in(1,5):
   n=8 if kind==1 else 4;value=b[p:p+n];p+=n
  else:raise ValueError((number,kind,p))
  result.append((number,kind,value))
 return result,p
def name(f):return next((v.decode() for n,k,v in f if n==1 and k==2),None)
for module in ['client','server']:
 b=Path('.agent-tmp/gotv-tools/cs2/game/csgo/bin/win64/'+module+'.dll').read_bytes()
 expected={'client':'659940c1db362ed981d1df10637cec8c2a3d99409b77fc3b73e435e4649e36b0','server':'09e8c04c5f44040155d04fa79a3f43491d542a386f45807ed77785729e5925a9'}
 assert hashlib.sha256(b).hexdigest()==expected[module]
 pattern=b'\x0a'+bytes([len('usermessages.proto')])+b'usermessages.proto';start=b.find(pattern);print(module,'descriptor',start)
 assert start>=0
 f,end=fields(b,start,min(len(b),start+65536));print('length',end-start,'fields',len(f));msgs=[];enums=[]
 for n,k,v in f:
  if n==4 and k==2:
   mf,_=fields(v);mn=name(mf)
   if mn in ['CUserMessageSayText','CUserMessageSayText2','CUserMessageSayTextChannel','CUserMessageTextMsg']:
    result=[]
    for nn,kk,vv in mf:
     if nn!=2 or kk!=2:continue
     ff,_=fields(vv);result.append({{1:'name',3:'tag',4:'label',5:'type',6:'type_name',7:'default'}[nn]:vv.decode() if kk==2 else vv for nn,kk,vv in ff if nn in [1,3,4,5,6,7]})
    msgs.append({'name':mn,'fields':result})
  if n==5 and k==2:
   ef,_=fields(v)
   for nn,kk,vv in ef:
    if nn==2 and kk==2:
     vf,_=fields(vv);nm=name(vf)
     if nm in ['UM_SayText','UM_SayText2','UM_SayTextChannel','UM_TextMsg']:enums.append({'name':nm,'id':next(x for a,c,x in vf if a==2)})
 result={'module':module,'module_sha256':expected[module],'descriptor_sha256':hashlib.sha256(b[start:end]).hexdigest(),'descriptor_offset':start,'descriptor_size':end-start,'messages':msgs,'enum':enums}
 Path('.agent-tmp/gotv-research-plan/'+module+'-chat-descriptor.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,ensure_ascii=False))
