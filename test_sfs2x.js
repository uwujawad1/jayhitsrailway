const SFS2X = require('sfs2x-api');

const config = {
    host: "app-demo.spribe.io",
    port: 443,
    useSSL: true,
    zone: "aviator_core",
    debug: true
};

console.log("Creating SmartFox client...");
const sfs = new SFS2X.SmartFox(config);

sfs.addEventListener(SFS2X.SFSEvent.CONNECTION, function(evtParams) {
    console.log("Connection event:", JSON.stringify(evtParams));
    if (evtParams.success) {
        console.log("Connected! Sending login...");
        sfs.send(new SFS2X.Requests.System.LoginRequest("", "", null, config.zone));
    }
});

sfs.addEventListener(SFS2X.SFSEvent.LOGIN, function(evtParams) {
    console.log("LOGIN SUCCESS! User:", evtParams.user ? evtParams.user.name : "unknown");
    console.log("Room list:", sfs.roomList.map(r => r.name));
});

sfs.addEventListener(SFS2X.SFSEvent.LOGIN_ERROR, function(evtParams) {
    console.log("Login error:", JSON.stringify(evtParams));
});

sfs.addEventListener(SFS2X.SFSEvent.CONNECTION_LOST, function(evtParams) {
    console.log("Connection lost:", JSON.stringify(evtParams));
});

sfs.addEventListener(SFS2X.SFSEvent.EXTENSION_RESPONSE, function(evtParams) {
    console.log("Extension response:", evtParams.cmd);
    if (evtParams.params) {
        try { console.log("Data:", evtParams.params.getDump()); } catch(e) { console.log("Data (raw):", evtParams.params); }
    }
});

sfs.addEventListener(SFS2X.SFSEvent.ROOM_JOIN, function(evtParams) {
    console.log("Room joined:", evtParams.room ? evtParams.room.name : "unknown");
});

sfs.addEventListener(SFS2X.SFSEvent.ROOM_ADD, function(evtParams) {
    console.log("Room added:", evtParams.room ? evtParams.room.name : "unknown");
});

sfs.addEventListener(SFS2X.SFSEvent.OBJECT_MESSAGE, function(evtParams) {
    console.log("Object message:", JSON.stringify(evtParams).substring(0, 500));
});

console.log("Connecting to", config.host + ":" + config.port);
sfs.connect();

setTimeout(() => {
    console.log("\nTimeout - disconnecting");
    try { sfs.disconnect(); } catch(e) {}
    process.exit(0);
}, 30000);
