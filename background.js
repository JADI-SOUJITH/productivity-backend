let currentTab = null;
let startTime = Date.now();
let isLiveEntry = false; // tracks if last entry in storage is a live (unsent) entry

// ================= SKIP INTERNAL URLS =================
function shouldTrack(url) {
    if (!url) return false;
    if (url.startsWith("chrome://")) return false;
    if (url.startsWith("chrome-extension://")) return false;
    if (url.startsWith("about:")) return false;
    if (url.startsWith("edge://")) return false;
    return true;
}

// ================= TAB SWITCH =================
chrome.tabs.onActivated.addListener(activeInfo => {
    chrome.tabs.get(activeInfo.tabId, tab => {
        if (!shouldTrack(tab.url)) return;
        savePrevious();
        currentTab = tab;
        startTime = Date.now();
        isLiveEntry = false;
    });
});

// ================= TAB UPDATE =================
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.status === "complete" && tab.active) {
        if (!shouldTrack(tab.url)) return;
        savePrevious();
        currentTab = tab;
        startTime = Date.now();
        isLiveEntry = false;
    }
});

// ================= SAVE COMPLETED SESSION =================
function savePrevious() {
    if (!currentTab || !shouldTrack(currentTab.url)) return;

    const endTime = Date.now();
    const duration = endTime - startTime;

    if (duration < 1000) return;

    const obj = {
        url: currentTab.url,
        title: currentTab.title || "",
        duration_ms: duration,
        start_time: new Date(startTime).toISOString(),
        end_time: new Date(endTime).toISOString()
    };

    chrome.storage.local.get("trackingData", (result) => {
        let data = result.trackingData || [];

        // If last entry was a live entry for this same tab, replace it
        // Otherwise push a new completed entry
        if (isLiveEntry && data.length > 0 && data[data.length - 1].url === obj.url) {
            data[data.length - 1] = obj;
        } else {
            data.push(obj);
        }

        isLiveEntry = false;
        chrome.storage.local.set({ trackingData: data });
    });
}

// ================= LIVE TRACK CURRENT TAB (every 10s) =================
// Updates the last entry with current ongoing duration
setInterval(() => {
    if (!currentTab || !shouldTrack(currentTab.url)) return;

    const now = Date.now();
    const duration = now - startTime;
    if (duration < 3000) return;

    const obj = {
        url: currentTab.url,
        title: currentTab.title || "",
        duration_ms: duration,
        start_time: new Date(startTime).toISOString(),
        end_time: new Date(now).toISOString()
    };

    chrome.storage.local.get("trackingData", (result) => {
        let data = result.trackingData || [];

        if (isLiveEntry && data.length > 0) {
            // Replace the existing live entry
            data[data.length - 1] = obj;
        } else {
            // Push a new live entry
            data.push(obj);
            isLiveEntry = true;
        }

        chrome.storage.local.set({ trackingData: data });
    });
}, 10000);

// ================= SEND TO BACKEND (every 15s) =================
// Only sends completed (non-live) entries to avoid sending partial data
setInterval(() => {
    chrome.storage.local.get("trackingData", (result) => {
        let data = result.trackingData || [];
        if (data.length === 0) return;

        // Don't send the last entry if it's a live in-progress entry
        const toSend = isLiveEntry ? data.slice(0, -1) : data;
        if (toSend.length === 0) return;

        fetch("https://productivity-backend-wayz.onrender.com/save", {  // <-- swap to your deployed URL
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(toSend)
        })
        .then(res => {
            if (res.ok) {
                console.log("🚀 Sent", toSend.length, "entries");
                // Keep only the live entry (if any) after successful send
                const remaining = isLiveEntry ? [data[data.length - 1]] : [];
                chrome.storage.local.set({ trackingData: remaining });
            }
        })
        .catch(err => console.error("❌ Send failed:", err));
    });
}, 15000);

// ================= INIT =================
chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
    if (tabs[0] && shouldTrack(tabs[0].url)) {
        currentTab = tabs[0];
        startTime = Date.now();
    }
});