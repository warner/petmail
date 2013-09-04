
console.log("control.js loaded");

function main() {
    console.log("onload");
    var ev = new EventSource("/api/v1/events/messages?token="+token);
    ev.onmessage = function(e) {
        var data = JSON.parse(e.data);
        console.log("event!", data.action, data.id, data.new_value);
        console.log("basic message", JSON.parse(data.payload_json).basic);
    };
}


document.addEventListener("DOMContentLoaded", main);
