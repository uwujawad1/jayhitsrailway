const WebSocket = require('ws');
global.WebSocket = WebSocket;
const SFS2X = require('sfs2x-api');
const https = require('https');

function httpsGetNoFollow(urlStr) {
    return new Promise((resolve, reject) => {
        const url = new URL(urlStr);
        https.request({hostname:url.hostname,path:url.pathname+url.search,headers:{"User-Agent":"Mozilla/5.0"},method:'GET'}, (res) => {
            let d=''; res.on('data',c=>d+=c); res.on('end',()=>resolve({status:res.statusCode,data:d,location:res.headers.location}));
        }).on('error',reject).end();
    });
}

function httpsGetJSON(urlStr) {
    return new Promise((resolve, reject) => {
        https.get(urlStr,{headers:{"User-Agent":"Mozilla/5.0"}},(res)=>{
            let d='';res.on('data',c=>d+=c);res.on('end',()=>{try{resolve(JSON.parse(d))}catch(e){reject(e)}});
        }).on('error',reject);
    });
}

async function tryLogin(server, user, operator, token, currency, lang, variant) {
    return new Promise((resolve) => {
        const sfs = new SFS2X.SmartFox({
            host: server.host, port: server.port,
            useSSL: server.useSSL, zone: server.zone, debug: false
        });
        let done = false;
        
        sfs.addEventListener(SFS2X.SFSEvent.CONNECTION, (e) => {
            if (!e.success) { resolve({ok:false,err:'conn_fail'}); return; }
            
            const params = new SFS2X.SFSObject();
            params.putUtfString("token", token);
            params.putUtfString("currency", currency);
            params.putUtfString("lang", lang);
            
            const platform = new SFS2X.SFSObject();
            platform.putUtfString("type", "Desktop");
            platform.putUtfString("device", "Desktop");
            params.putSFSObject("platform", platform);
            
            // Try different username formats
            let username;
            switch(variant) {
                case 1: username = `${user}&&${operator}`; break;
                case 2: username = String(user); break;
                case 3: username = `${user}&&${operator}&&${currency}`; break;
                case 4: username = `guest_${user}`; break;
            }
            
            console.log(`  [v${variant}] Login: ${username} zone=${server.zone}`);
            sfs.send(new SFS2X.LoginRequest(username, "", params));
        });
        
        sfs.addEventListener(SFS2X.SFSEvent.LOGIN, (e) => {
            done = true;
            console.log(`  [v${variant}] *** SUCCESS! *** User: ${sfs.mySelf?.name}`);
            console.log(`  Rooms: ${sfs.roomList.length}`);
            sfs.roomList.forEach(r => console.log(`    ${r.name} (${r.userCount} users)`));
            
            // Join the first room
            if (sfs.roomList.length > 0) {
                sfs.send(new SFS2X.JoinRoomRequest(sfs.roomList[0]));
            }
            
            // Listen for game data
            setTimeout(() => { sfs.disconnect(); resolve({ok:true}); }, 20000);
        });
        
        sfs.addEventListener(SFS2X.SFSEvent.LOGIN_ERROR, (e) => {
            console.log(`  [v${variant}] Error: ${e.errorMessage} (${e.errorCode})`);
            try{sfs.disconnect();}catch(x){}
            resolve({ok:false,err:e.errorMessage,code:e.errorCode});
        });
        
        sfs.addEventListener(SFS2X.SFSEvent.CONNECTION_LOST, (e) => {
            if(!done) resolve({ok:false,err:'lost'});
        });
        
        sfs.addEventListener(SFS2X.SFSEvent.EXTENSION_RESPONSE, (e) => {
            console.log(`\n  EXT [${e.cmd}]`);
            try { console.log("  " + e.params.getDump().substring(0,3000)); } catch(x){}
        });
        
        sfs.addEventListener(SFS2X.SFSEvent.ROOM_JOIN, (e) => {
            console.log(`\n  Joined: ${e.room?.name}`);
            try {
                const vars = e.room.getVariables();
                vars?.forEach(v => console.log(`    VAR ${v.name}: ${JSON.stringify(v.value).substring(0,500)}`));
            } catch(x) {}
        });
        
        sfs.addEventListener(SFS2X.SFSEvent.ROOM_VARIABLES_UPDATE, (e) => {
            try {
                e.changedVars?.forEach(vn => {
                    const v = e.room?.getVariable(vn);
                    console.log(`  VAR_UPD ${vn}: ${JSON.stringify(v?.value).substring(0,500)}`);
                });
            } catch(x) {}
        });
        
        sfs.connect();
        setTimeout(() => { if(!done){try{sfs.disconnect();}catch(x){}} resolve({ok:false,err:'timeout'}); }, 8000);
    });
}

async function main() {
    console.log("Getting fresh demo token...");
    const resp = await httpsGetNoFollow("https://demo.spribe.io/launch/aviator");
    const url = new URL(resp.location);
    const token = url.searchParams.get('token');
    const user = url.searchParams.get('user');
    const operator = url.searchParams.get('operator');
    const currency = url.searchParams.get('currency');
    const lang = url.searchParams.get('lang');
    console.log(`Token: ${token} User: ${user} Op: ${operator}`);
    
    const config = await httpsGetJSON(`https://app-config.spribegaming.com/aviator/${operator}.json`);
    const server = config.servers[0]; // app-demo2
    
    for (let v = 1; v <= 4; v++) {
        const result = await tryLogin(server, user, operator, token, currency, lang, v);
        if (result.ok) break;
    }
    
    process.exit(0);
}

main().catch(e => { console.error(e); process.exit(1); });
