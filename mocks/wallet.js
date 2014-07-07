
console.log("wallet.js loaded");

var image_b64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAAADnUlEQVR4nO3TSZLcMBBDUd3/0vbSi1a5QAjg0PoZwZ2YE5+u67r+rDqpcPK2+nfurXyDCwAAAAAAAACA8KMoQyaW59aeBdSduxUAAAAAAAAAAAAAADKAxPJWfmMupnZSczuAAfAhAAAAAAAAALHlpIZ0eknFaXMDAAAAAAAAbmdw4rS5AQCA3weg1Z+TtxUAGKiT6g8AAAAAAAAgAVg5ZKrWaXlbAYBD8rYCAIfkbQUADsnbiq8AZh5nEc43yiKcb5ozTTwAAAAAAAAAAADgjQBuJ98onIdKYHR7OS22nwIA3dh+CgB0Y/spANANaYrEslLHqeX26+xh1kyp/QHgPzmcPQBg8gBKLbdfZw8AmDyAUsvt19kDACYPoNRy+3X2cBwApxlnoc4d9Z4T7sMk6qT6C+UFAAAAAAAAvBTArKGcge7yOt8o/bhzO/2u2sPtkSY3iqcWkRhc6cedGwAAAAAAABBZHgAWADjtEZQ8iQW7/bZqpfLe1AEAAABg1XF7ac3kBADeDsC6FFi4Cmtmnhlo3H5beQEAgPEAAAAA8CYAqWU4dXaKFpJZvQDgYQAAAAAAAAAA8DYArYZrQ4UeKnHHyevuxnoH6VYgADA2Z+KOVFu6FQgAjM2ZuCPVlm4FAgBjcybuSLWlW0Iz375R8ri1neUl8rozOXmdkOauJQYAAAAAAACE5nYCAA/6BcDDYlYz5tKVPAkAznH7a2AEAAB+fjO2Wr2Y1QwAAACAxQCaDTkNOwtt5W09TCqst4skAQAAZg2g3GvlBQAAfh+A1lCz0NzVdnpL1E3CGp3RrQMAAAAAAACI1AUAAM4D4CRyiqUWYQ8a6K8VDgD3zo9vnAbVIQCgBQAAAAAALAKQeoSJDdce/Fut1NytY/YCAHWG1NwAAAAAAAAA6U5rwc4Mqbm3AiBNNSlS+JS8rcdtzZTaCwAAAAAAAAAA/873oVpHWVbioczFDC32yQyp3Sj9A0C8AwAASPcSMwDgwfKUIZ07AACAdC8xw1YAWpFahJp7dBGtvC1YbgDgw51WXgB8Lmx9o+YGgJYHAADIDNV6XHOoyNmpl8aPAQAAAAAAAADAzgBaaJxI9bLTzgEwEAAAAAAAAAAAAKDWzHBeZaFu3tE6yh23v9Y7AQAAAAAAAG7zjtZR7hwJIBHu0p3cbj+Jk6rt5HACAAAAAAAAAAAAAGD6SUWrl1b/O9UGwAaPsLI2ADZ4hJW1AbDBI6ys/Rc+fogX75a+3AAAAABJRU5ErkJggg==";

function handlePaymentFile(paymentfile) {
  var payment_data;
  var r = new FileReader();
  r.onload = function(e) {
    //payment_data = e.target.result;
    payment_data = this.result; // data:image/jpeg;base64,..
    if (payment_data) {
      console.log(" 'payment' received");
      showInvitation();
    }
  };
  r.readAsDataURL(paymentfile);
}

function main() {
  console.log("onload");

  $("#spend-qrcode").hide();
  $("input#spend").on("click", function() {
    if (0) {
      $("#spend-qrcode")
        .empty()
        .qrcode({width: 128, height: 128, text: "0.001 BTC privkey"})
        .show();
    }
    if (1) {
      $("#spend-qrcode")
        .empty()
        .append($("<img>").attr("src", image_b64))
        .show()
      ;
    }
  });
  console.log("setup done");
}


document.addEventListener("DOMContentLoaded", main);
