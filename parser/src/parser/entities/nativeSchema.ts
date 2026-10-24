import type { CSVCMsg_FlattenedSerializer, ProtoFlattenedSerializerField_t } from '../../ts-proto/netmessages.js';
import { createNativeFieldCodec, nativeCoordinateProfile, type NativeCodec, type NativeCoordinateProfile, type NativeFieldEncoding } from './nativeFieldCodec.js';
import { nativePrimitiveTypes, nativeCustomTypes, nativeEnumSignedness, nativeTypeAliases, isNativePointerFieldName, nativeFieldSerializerFallbacks, nativeBoxedTypes } from './nativeSchemaProfile.js';

export type NativeSchemaField = Readonly<{
 name:string;sendNode:string;typeName:string;baseType:string;customSerializer:string|undefined;declaredCustomSerializer:string|undefined;
 container:Readonly<{kind:'fixed';size:number}|{kind:'vector'}>|undefined;
 kind:'scalar'|'struct'|'pointer';serializer:string|undefined;variants:readonly string[];
 encoding:NativeFieldEncoding|undefined;codec:NativeCodec|undefined;
}>;
export type NativeSerializer = Readonly<{name:string;version:number;fields:readonly NativeSchemaField[]}>;
export type NativeMetadata = Readonly<{kind:0|1;value:number}>;
export type NativeAncestor = Readonly<{
 kind:'array'|'pointer';field:NativeSchemaField;path:readonly number[];
}>;
export type NativeResolvedPath = Readonly<{
 field:NativeSchemaField;operation:'value'|'pointer'|'array';path:readonly number[];ancestors:readonly NativeAncestor[];
}>;
const vectorNames=new Set(['CNetworkUtlVectorBase','CUtlVectorEmbeddedNetworkVar','C_NetworkUtlVectorBase','C_UtlVectorEmbeddedNetworkVar','CUtlVector']);
// Fixed native custom registry and compatibility field lookup are case-insensitive.
const customNames=new Map(Object.keys(nativeCustomTypes).map(name=>[name.toLowerCase(),name]));
const primitiveNames=new Map(Object.entries(nativePrimitiveTypes).map(([name,type])=>[name.toLowerCase(),type]));
const enumNames=new Map(Object.entries(nativeEnumSignedness).map(([name,signed])=>[name.toLowerCase(),signed]));
const boxedNames=new Map(Object.entries(nativeBoxedTypes).map(([name,type])=>[name.toLowerCase(),type]));
const fieldFallbacks=new Map(Object.entries(nativeFieldSerializerFallbacks).map(([name,value])=>[name.toLowerCase(),value]));
const key=(name:string,version:number)=>{
 if(!name||name.includes('\0')||!Number.isInteger(version)||version<0||version>0x7fffffff)throw new Error('Invalid serializer identity');
 return name.toLowerCase()+'\0'+version;
};
function shape(type:string):{element:string;container:NativeSchemaField['container'];atomicString?:boolean} {
 const value=type.trim(),array=/^(.*)\[(\d+)\]$/.exec(value);
 if(array){
  const element=array[1]!.trim(),size=Number(array[2]);
  if(!Number.isSafeInteger(size)||size<1||size>32767)throw new Error('Fixed array extent budget');
  if(/\[\d+\]$/.test(element))throw new Error('Unsupported nested fixed array shape');
  if(element==='char'&&size>1)return {element:'char',container:undefined,atomicString:true};
  return {element,container:Object.freeze({kind:'fixed',size})};
 }
 const open=value.indexOf('<');
 if(open>=0&&vectorNames.has(value.slice(0,open).trim())){
  if(!value.endsWith('>'))throw new Error('Malformed vector type');
  const args=value.slice(open+1,-1);let depth=0,end=args.length;
  for(let i=0;i<args.length;i++){
   if(args[i]==='<')depth++;else if(args[i]==='>'){if(--depth<0)throw new Error('Malformed vector argument');}
   else if(args[i]===','&&depth===0){end=i;break;}
  }
  if(depth!==0)throw new Error('Malformed vector argument');
  const element=args.slice(0,end).trim();if(!element)throw new Error('Missing vector element');
  return {element,container:Object.freeze({kind:'vector'})};
 }
 return {element:value,container:undefined};
}
function remap(type:string):string {
 let current=type;
 for(let n=0;n<16;n++){
  const rule=nativeTypeAliases.find(r=>r.prefix?current.toLowerCase().startsWith(r.from.toLowerCase()):current===r.from);
  if(!rule||rule.to===current)return current;
  current=rule.to;
 }
 throw new Error('Type alias recursion budget');
}
/** Immutable graph with lazy pointer/vector cycles and entity-local variant lookup. */
export class NativeSchema {
 readonly coordinateProfile:NativeCoordinateProfile;
 readonly classIdBits:number;
 private readonly serializers:Map<string,NativeSerializer>;
 private readonly classes:Map<number,string>;
 constructor(message:CSVCMsg_FlattenedSerializer,classes:readonly {class_id?:number;network_name?:string}[],maxClasses:number){
  if(!Number.isSafeInteger(maxClasses)||maxClasses<1||maxClasses>65536)throw new Error('Class count budget');
  if(message.symbols.length>250000||message.fields.length>100000||message.serializers.length>8192||classes.length>maxClasses)throw new Error('Schema graph budget');
  this.classIdBits=32-Math.clz32(maxClasses);this.coordinateProfile=nativeCoordinateProfile(message.coord_size_params);
  const symbol=(index:number|undefined,required=true):string|undefined=>{
   if(index===undefined){if(required)throw new Error('Missing schema symbol');return undefined;}
   if(!Number.isInteger(index)||index<0||index>=message.symbols.length)throw new Error('Invalid schema symbol index');
   const value=message.symbols[index]!;if(typeof value!=='string'||value.length>4096||value.includes('\0'))throw new Error('Invalid schema symbol');
   return value;
  };
  const nodes=new Map<string,{name:string;version:number;fieldIndices:readonly number[]}>();let refs=0;
  for(const s of message.serializers){
   const name=symbol(s.serializer_name_sym)!,version=s.serializer_version??0,id=key(name,version);

   refs+=s.fields_index.length;if(refs>1000000)throw new Error('Serializer reference budget');
   const indices=s.fields_index.map(i=>{if(!Number.isInteger(i)||i<0||i>=message.fields.length)throw new Error('Invalid serializer field index');return i;});
   const previous=nodes.get(id);
   if(previous&&(previous.fieldIndices.length!==indices.length||previous.fieldIndices.some((v,i)=>v!==indices[i])))throw new Error('Conflicting duplicate serializer identity');
   if(!previous)nodes.set(id,{name,version,fieldIndices:indices});
  }
  const reference=(nameIndex:number|undefined,version:number|undefined):string|undefined=>{
   if(nameIndex===undefined)return undefined;
   const id=key(symbol(nameIndex)!,version??0);if(!nodes.has(id))throw new Error('Unresolved versioned serializer');return id;
  };
  const buildField=(f:ProtoFlattenedSerializerField_t):NativeSchemaField=>{
   const name=symbol(f.var_name_sym)!,typeName=symbol(f.var_type_sym)!;
   const send=symbol(f.send_node_sym,false),sendNode=!send||send==='(root)'?'':send;
   const parsed=shape(typeName),pointer=parsed.element.endsWith('*')||isNativePointerFieldName(name);
   const element=parsed.element.endsWith('*')?parsed.element.slice(0,-1).trim():parsed.element;
   const baseType=remap(element),serializer=reference(f.field_serializer_name_sym,f.field_serializer_version);
   const variants=Object.freeze(f.polymorphic_types.map(v=>{
    const id=reference(v.polymorphic_field_serializer_name_sym,v.polymorphic_field_serializer_version);
    if(id===undefined)throw new Error('Missing polymorphic serializer');return id;
   }));
   if(variants.length>8192)throw new Error('Polymorphic type budget');
   const explicitCustom=symbol(f.var_serializer_sym,false);
   const customSerializer=(explicitCustom===undefined?undefined:customNames.get(explicitCustom.toLowerCase()))??fieldFallbacks.get(name.toLowerCase());
   let encoding:NativeFieldEncoding|undefined,codec:NativeCodec|undefined;
   const kind=serializer?(pointer?'pointer':'struct'):'scalar';
   if(kind==='scalar'){
    if(variants.length)throw new Error('Polymorphic scalar has no serializer');
    let type;
    if(f.var_enum_info!==undefined)type={category:f.var_enum_info.is_signed_enum?1:2,dimensions:1};
    else if(enumNames.has(baseType.toLowerCase()))type={category:enumNames.get(baseType.toLowerCase())?1:2,dimensions:1};
    else {
     const normalized=boxedNames.get(baseType.toLowerCase())??(baseType.startsWith('CStrongHandle')?'uint64':baseType==='CNetworkedQuantizedFloat'?'float32':baseType);
     type=parsed.atomicString?{category:5,dimensions:1}:primitiveNames.get(normalized.toLowerCase());
    }
    // An explicitly recognized custom serializer provides its own proven wire
    // category. This is not a generic integer fallback for an unknown type.
    if(customSerializer)type=nativeCustomTypes[customSerializer]??type;
    if(!type)throw new Error('Unsupported native field type: '+baseType);
    encoding=Object.freeze({category:type.category,dimensions:type.dimensions,encoder:symbol(f.var_encoder_sym,false)??'default',
     bit_count:f.bit_count,encode_flags:f.encode_flags,low_value:f.low_value,high_value:f.high_value});
    codec=createNativeFieldCodec(encoding,this.coordinateProfile);
   }else if(variants.length&&kind!=='pointer')throw new Error('Unsupported by-value polymorphic field');
   return Object.freeze({name,sendNode,typeName,baseType,customSerializer,declaredCustomSerializer:explicitCustom,container:parsed.container,kind,serializer,variants,encoding,codec});
  };
  this.serializers=new Map();this.classes=new Map();
  for(const c of classes){
   if(!Number.isInteger(c.class_id)||c.class_id!<0||c.class_id!>=maxClasses||!c.network_name||this.classes.has(c.class_id!))throw new Error('Invalid class declaration');
   const id=key(c.network_name,0);if(!nodes.has(id))throw new Error('Missing version0 class root');this.classes.set(c.class_id!,id);
  }
  const built=new Map<number,NativeSchemaField>(),queue=[...new Set(this.classes.values())],queued=new Set(queue);
  const enqueue=(id:string)=>{if(!queued.has(id)){queued.add(id);queue.push(id);}};
  for(let i=0;i<queue.length;i++){
   const id=queue[i]!;if(this.serializers.has(id))continue;
   const node=nodes.get(id)!;
   const fields=node.fieldIndices.map(index=>{
    let field=built.get(index);if(!field){field=buildField(message.fields[index]!);built.set(index,field);}
    return field;
   });
   this.serializers.set(id,Object.freeze({name:node.name,version:node.version,fields:Object.freeze(fields)}));
   for(const field of fields){if(field.serializer)enqueue(field.serializer);for(const variant of field.variants)enqueue(variant);}
   if(queue.length>1000000)throw new Error('Schema traversal budget');
  }
  const visiting=new Set<string>(),visited=new Set<string>();
  for(const first of this.serializers.keys()){
   if(visited.has(first))continue;
   const stack:{id:string;exit:boolean}[]=[{id:first,exit:false}];
   while(stack.length){
    const current=stack.pop()!;
    if(current.exit){visiting.delete(current.id);visited.add(current.id);continue;}
    if(visiting.has(current.id))throw new Error('Recursive by-value serializer');if(visited.has(current.id))continue;
    visiting.add(current.id);stack.push({id:current.id,exit:true});
    for(const field of this.serializers.get(current.id)!.fields)if(field.kind==='struct'&&field.container?.kind!=='vector')stack.push({id:field.serializer!,exit:false});
   }
  }
 }
 getClass(classId:number):NativeSerializer {
  const id=this.classes.get(classId);if(id===undefined)throw new Error('Unknown class ID');return this.serializers.get(id)!;
 }
 resolve(classId:number,path:readonly number[],metadata:(prefix:readonly number[])=>NativeMetadata|undefined):NativeResolvedPath {
  if(path.length<1||path.length>10||path[0]===32767||path.some(i=>!Number.isInteger(i)||i<0||i>32767))throw new Error('Invalid field path');
  let node=this.getClass(classId),cursor=0;
  const ancestors:NativeAncestor[]=[];
  const resolved=(field:NativeSchemaField,operation:NativeResolvedPath['operation']):NativeResolvedPath=>
   Object.freeze({field,operation,path:Object.freeze([...path]),ancestors:Object.freeze(ancestors)});
  while(cursor<path.length){
   const field=node.fields[path[cursor]!];if(!field)throw new Error('Unresolved field path');
   const prefix=path.slice(0,cursor+1);cursor++;
   if(field.container){
    if(cursor===path.length)return resolved(field,'array');
    ancestors.push(Object.freeze({kind:'array',field,path:Object.freeze(prefix)}));
    const index=path[cursor++]!,known=metadata(prefix);
    const size=field.container.kind==='fixed'?field.container.size:known?.kind===0?known.value:undefined;
    if(size!==undefined&&(!Number.isSafeInteger(size)||size<0||index>=size))throw new Error('Array field path out of bounds');
   }
   if(cursor===path.length){
    if(field.kind==='struct')throw new Error('Field path ends at by-value serializer');
    return resolved(field,field.kind==='pointer'?'pointer':'value');
   }
   if(!field.serializer)throw new Error('Scalar field path has descendants');
   if(field.kind==='pointer')ancestors.push(Object.freeze({kind:'pointer',field,path:Object.freeze(path.slice(0,cursor))}));
   let target=field.serializer;
   if(field.variants.length){
    const active=metadata(path.slice(0,cursor));
    if(active?.kind===1){
     if(!Number.isInteger(active.value)||active.value<1||active.value>field.variants.length)throw new Error('Invalid active polymorphic selector');
     target=field.variants[active.value-1]!;
    }
   }
   node=this.serializers.get(target)!;
  }
  throw new Error('Incomplete field path');
 }
}
