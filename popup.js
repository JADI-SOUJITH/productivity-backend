document.getElementById("downloadBtn").addEventListener("click", async () => {
    // FIX: was reading "data" but background.js writes to "trackingData"
    const result = await chrome.storage.local.get("trackingData");
    const data = result.trackingData || [];

    const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json"
    });

    const url = URL.createObjectURL(blob);

    chrome.downloads.download({
        url: url,
        filename: "productivity_data.json"
    });
});