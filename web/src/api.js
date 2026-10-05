import {SUPABASE_PUBLISHABLE_KEY,SUPABASE_URL} from "./config.js";

export async function signIn(email,password,fetchImpl=fetch){
  const response=await fetchImpl(`${SUPABASE_URL}/auth/v1/token?grant_type=password`,{method:"POST",headers:{apikey:SUPABASE_PUBLISHABLE_KEY,"Content-Type":"application/json"},body:JSON.stringify({email,password})});
  const payload=await response.json().catch(()=>({}));
  if(!response.ok||typeof payload.access_token!=="string") throw new Error("invalid_credentials");
  return {accessToken:payload.access_token,email:payload.user?.email||email};
}
export async function apiRequest(path,token,options={},fetchImpl=fetch){
  const headers={Authorization:`Bearer ${token}`,...(options.body?{"Content-Type":"application/json"}:{}),...(options.headers||{})};
  const response=await fetchImpl(path,{...options,headers});
  const payload=await response.json().catch(()=>({ok:false,error:"invalid_response"}));
  if(!response.ok||payload.ok===false){const error=new Error(payload.error||`http_${response.status}`);error.status=response.status;error.code=payload.error||"request_failed";error.detail=payload.detail||"";throw error;}
  return payload;
}
export function csv(value){return String(value||"").split(",").map(x=>x.trim()).filter(Boolean);}
export function formatDate(value){if(!value)return "—";const d=new Date(value);return Number.isNaN(d.getTime())?String(value):d.toLocaleString();}
