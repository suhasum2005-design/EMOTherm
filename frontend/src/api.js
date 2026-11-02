let token=null;
let refreshing=null;
export function setToken(value){token=value;}
export async function refreshSession(){
  if(!refreshing) refreshing=fetch('/api/auth/refresh',{method:'POST',credentials:'include'}).then(async r=>{if(!r.ok)throw new Error('Sign in required');const data=await r.json();token=data.access_token;return data;}).finally(()=>{refreshing=null;});
  return refreshing;
}
export async function api(path,options={},retry=true){
  const headers={...options.headers};
  if(token)headers.Authorization=`Bearer ${token}`;
  if(options.body && !(options.body instanceof FormData))headers['Content-Type']='application/json';
  const response=await fetch('/api'+path,{...options,headers,credentials:'include'});
  if(response.status===401 && retry && !path.startsWith('/auth/')){
    try{await refreshSession();return api(path,options,false);}catch{token=null;window.dispatchEvent(new Event('session-expired'));}
  }
  if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{detail=response.statusText;}throw new Error(typeof detail==='string'?detail:'Please check the form values.');}
  if(options.blob)return response.blob();
  return response.json();
}
export const post=(path,body)=>api(path,{method:'POST',body:body===undefined?undefined:JSON.stringify(body)});
