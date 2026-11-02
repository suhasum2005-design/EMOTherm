import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
function inlineRuntimeEnvironment(){
  let production=false;
  return {name:'inline-runtime-environment',enforce:'pre',configResolved(config){production=config.command==='build';},
    transform(code,id){
      if(!/\.[cm]?jsx?(\?|$)/.test(id)||(!code.includes('process.env')&&!(production&&code.includes('import.meta.hot'))))return;
      let result=code.replaceAll('process.env.NODE_ENV',JSON.stringify(production?'production':'development')).replaceAll('process.env','({})');
      if(production)result=result.replaceAll('import.meta.hot','undefined');
      return {code:result,map:null};
    }};
}
// In-process Babel transformation avoids native esbuild child processes on restricted Windows hosts.
export default defineConfig({
  plugins:[react({babel:{plugins:[['@babel/plugin-transform-react-jsx',{runtime:'automatic'}]]}}),inlineRuntimeEnvironment(),tailwindcss(),{name:'in-process-transform',config:()=>({esbuild:false})}],
  esbuild:false,
  resolve:{preserveSymlinks:true},
  optimizeDeps:{noDiscovery:true,include:[]},
  build:{target:'esnext',minify:false,rollupOptions:{output:{manualChunks:{charts:['recharts'],motion:['framer-motion']}}}},
  server:{proxy:{'/api':{target:'http://127.0.0.1:8000',ws:true}}}
});
