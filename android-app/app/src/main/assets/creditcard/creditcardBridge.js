(function() {
    if (window._androidPostMessageInjected) return;
    window._androidPostMessageInjected = true;

    window.addEventListener("message", function(event) {
        var baseUrl = window._baseUrl
        if (event.origin !== baseUrl) {
          console.error("Origin is invalid.");
          return;
        }
        try {
            var data = (typeof event.data === "object")
                ? JSON.stringify(event.data)
                : String(event.data);

            if (window.AndroidBridge && AndroidBridge.onMessageFromJs) {
                AndroidBridge.onMessageFromJs(data);
            }
        } catch (e) {
            console.error("Error sending event to AndroidBridge", e);
        }
    }, false);
})();

window.submitForm = function(url) {
  document.querySelector('#iFrameUrl').contentWindow.postMessage({action: 'submit'}, url);
}
