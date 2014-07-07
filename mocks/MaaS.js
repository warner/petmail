
console.log("MaaS.js loaded");

function handlePaymentFile(paymentfile) {
  var payment_data;
  var r = new FileReader();
  r.onload = function(e) {
    //payment_data = e.target.result;
    payment_data = this.result; // data:image/jpeg;base64,..
    if (payment_data) {
      handlePaymentDataURI(payment_data);
    }
  };
  r.readAsDataURL(paymentfile);
}

function handlePaymentDataURI(data_uri) {
  console.log(" 'payment' received", data_uri);
  showInvitation();
}

function showInvitation() {
  $("div.payment-drop").hide("clip");
  $("div.invitation-code-display").show("clip");
  $("span.invitation-code").text("mailbox12345678");
}

var stash;
function main() {
  console.log("onload");

  $("div.payment-drop").show();
  $("div.invitation-code-display").hide();

  var dropper = $("div.payment-drop");
  dropper.bind({
    drop: function(e) {
      //e.stopPropagation();
      //e.preventDefault();
      console.log("drop", e, e.originalEvent);
      stash = e;
      var dt = e.originalEvent.dataTransfer;
      if (dt.types.contains("Files")) {
        var file = dt.files[0];
        var validTypes = ["image/jpeg", "image/png", "image/gif"];
        if (validTypes.indexOf(file.type) == -1) {
          alert("payment icon must be image/jpeg, image/png, or image/gif");
          return false;
        }
        handlePaymentFile(file);
      } else if (dt.types.contains("text/uri-list")) {
        var data_uri = dt.getData("text/uri-list");
        handlePaymentDataURI(data_uri);
      }
      return false;
    },
    dragenter: function(e) {e.stopPropagation();
                            e.preventDefault();
                            return false;},
    dragover: function(e) {e.stopPropagation();
                           e.preventDefault();
                           return false;}
  });

  console.log("setup done");
}


document.addEventListener("DOMContentLoaded", main);
