// ==UserScript==
// @name         Elvenar Radar
// @namespace    http://tampermonkey.net/
// @version      6.7.6
// @description  Silent background tracker that live-updates Elvenar military, workshops, Power of Provision spell, AWs, and Pet Food buffs to Telegram with Event-Driven Realtime Mini App (<1s sync) - Single Pinned Message Only
// @updateURL    https://phusi319.github.io/elvenar-dashboard/elvenar-radar.user.js
// @downloadURL  https://phusi319.github.io/elvenar-dashboard/elvenar-radar.user.js
// @match        https://*.elvenar.com/*
// @connect      elvenar-radar-default-rtdb.europe-west1.firebasedatabase.app
// @connect      elvenar-radar.phusi-319.workers.dev
// @connect      api.telegram.org
// @connect      *
// @grant        unsafeWindow
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_registerMenuCommand
// @run-at       document-start
// ==/UserScript==

(function() {
    'use strict';

    // =========================================================================
    // ⚙️ REALTIME DATABASE SETTINGS (GOOGLE FIREBASE & CLOUDFLARE BACKUP)
    // =========================================================================
    const FIREBASE_DATABASE_URL = "https://elvenar-radar-default-rtdb.europe-west1.firebasedatabase.app/live.json";
    const CLOUDFLARE_WORKER_URL = "https://elvenar-radar.phusi-319.workers.dev/";

    // =========================================================================
    // 🛡️ ZERO-LEAK TELEGRAM SECURITY (LƯU TRÊN MÁY BẢO VỆ CHỐNG QUÉT GITHUB)
    // =========================================================================
    // Token được lưu an toàn trong bộ nhớ Tampermonkey của trình duyệt (GM_getValue).
    // KHÔNG BAO GIỜ bị lộ lên GitHub công khai và KHÔNG BỊ MẤT khi script tự động cập nhật!
    let TELEGRAM_BOT_TOKEN = (GM_getValue("ELVENAR_TELEGRAM_BOT_TOKEN", "") || "").trim();

    // Menu Tampermonkey hỗ trợ đổi Token bất kỳ lúc nào
    if (typeof GM_registerMenuCommand !== 'undefined') {
        GM_registerMenuCommand("🔑 Cấu hình Telegram Bot Token", () => {
            const currentToken = GM_getValue("ELVENAR_TELEGRAM_BOT_TOKEN", "");
            const tokenInput = prompt(
                "🔑 NHẬP TELEGRAM BOT TOKEN MỚI:\n(Token lưu an toàn trong máy bạn, không bị ghi đè khi script auto-update)",
                currentToken
            );
            if (tokenInput !== null) {
                const clean = tokenInput.trim();
                GM_setValue("ELVENAR_TELEGRAM_BOT_TOKEN", clean);
                TELEGRAM_BOT_TOKEN = clean;
                alert(clean ? "✅ Đã lưu Telegram Bot Token thành công!" : "⚠️ Đã xóa Token.");
            }
        });
    }

    // Nhắc nhở dán Token một lần duy nhất nếu chưa có hoặc dính token cũ bị hủy
    if (!TELEGRAM_BOT_TOKEN || TELEGRAM_BOT_TOKEN.startsWith("8800181376:AAG2Oe")) {
        setTimeout(() => {
            const current = (GM_getValue("ELVENAR_TELEGRAM_BOT_TOKEN", "") || "").trim();
            if (!current || current.startsWith("8800181376:AAG2Oe")) {
                const tokenInput = prompt(
                    "🛡️ [Elvenar Live Radar] Vui lòng dán Telegram Bot Token mới của bạn để kích hoạt thông báo Telegram:\n(Lưu an toàn trong máy bạn, không bao giờ bị lộ lên GitHub dù script có auto-update)",
                    ""
                );
                if (tokenInput && tokenInput.trim()) {
                    const clean = tokenInput.trim();
                    GM_setValue("ELVENAR_TELEGRAM_BOT_TOKEN", clean);
                    TELEGRAM_BOT_TOKEN = clean;
                    alert("✅ Đã lưu Telegram Bot Token an toàn vào trình duyệt!");
                }
            }
        }, 3500);
    }

    const TELEGRAM_CHAT_ID = "-1003909496356"; // Topic 26 (Group - Cập nhật text, KHÔNG GHIM)
    const TELEGRAM_TOPIC_ID = 26;
    const TELEGRAM_PRIVATE_CHAT_ID = "7620170971"; // Chat riêng với Bot
    const TELEGRAM_SYNC_INTERVAL_SEC = 45; // Chu kỳ nhịp tim định kỳ khi treo máy (giây) - Hành động trong game vẫn bắn tức thì (<1.5s)

    // Đường dẫn Telegram Mini App Native (Mở trực tiếp trong Topic hoặc Chat riêng)
    const MINI_APP_GROUP_URL = "https://t.me/ElvenTreasureBot/radar?startapp=live";
    const MINI_APP_WEB_URL = "https://phusi319.github.io/elvenar-dashboard/?v=fb1";

    const win = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;

    let liveGroupMsgId = GM_getValue("ELVENAR_LIVE_GROUP_MSG_ID", 1038);
    let livePrivateMsgId = GM_getValue("ELVENAR_LIVE_PRIVATE_MSG_ID", 27);

    // --- 1. DỮ LIỆU QUẢN LÝ (KHÔI PHỤC TỪ CACHE GM_VALUE NẾU CÓ) ---
    let savedMil = null;
    try { savedMil = JSON.parse(GM_getValue("ELVENAR_TRACKED_MIL", "null")); } catch(e) {}
    const militaryQueues = savedMil || {
        "military_production": { name: "Barracks", slots: [], maxSlots: 5, totalFinishTime: 0, firstSlotFinishTime: 0 },
        "training_grounds_production": { name: "Training Grounds", slots: [], maxSlots: 5, totalFinishTime: 0, firstSlotFinishTime: 0 },
        "mercenary_camp_production": { name: "Mercenary Camp", slots: [], maxSlots: 5, totalFinishTime: 0, firstSlotFinishTime: 0 }
    };

    let savedAWs = null;
    try { savedAWs = JSON.parse(GM_getValue("ELVENAR_TRACKED_AWS", "null")); } catch(e) {}
    const trackedAWs = savedAWs || {
        "b_all_aw2": { name: "Golden Abyss", level: 0, status: "Idle", finishTime: 0, uid: null },
        "b_fairies_aw1": { name: "Prosperity Towers", level: 0, status: "Idle", finishTime: 0, uid: null },
        "b_gr5_aw1": { name: "Maze of the Dark Matter", level: 0, status: "Idle", finishTime: 0, uid: null }
    };

    let savedPets = null;
    try { savedPets = JSON.parse(GM_getValue("ELVENAR_TRACKED_PETS", "null")); } catch(e) {}
    const trackedPets = savedPets || {
        "unit_production_pickup_boost": { name: "Brown Bear", finishTime: 0 },
        "training_speed_bonus": { name: "Shellux", finishTime: 0 }
    };

    let savedWS = null;
    try { savedWS = JSON.parse(GM_getValue("ELVENAR_TRACKED_WS", "null")); } catch(e) {}
    let workshops = savedWS || {};

    const petEntityMap = {};
    let wsStoppedSince = Number(GM_getValue("ELVENAR_WS_STOPPED_SINCE", 0));
    let myPlayerId = GM_getValue("ELVENAR_MY_PLAYER_ID", null);
    let provisionSpellFinishTime = Number(GM_getValue("ELVENAR_PROVISION_SPELL_FINISH", 0));
    // Dọn dẹp mốc rác 32 ngày cũ do lỗi confId 201 gây ra (chạy 1 lần duy nhất để giải phóng bộ nhớ sạch sẽ)
    if (!GM_getValue("ELVENAR_PROVISION_CLEANED_V625", false)) {
        provisionSpellFinishTime = 0;
        try {
            GM_setValue("ELVENAR_PROVISION_SPELL_FINISH", 0);
            GM_setValue("ELVENAR_PROVISION_CLEANED_V625", true);
        } catch(e) {}
    }

    let savedArmy = null;
    try { savedArmy = JSON.parse(GM_getValue("ELVENAR_TRACKED_ARMY", "null")); } catch(e) {}
    let trackedArmy = savedArmy || {
        squadSize: 0,
        squads: {},
        raw: {}
    };
    if (trackedArmy && Array.isArray(trackedArmy.buffs) && !Array.isArray(trackedArmy.spireBuffs) && Number(trackedArmy.buffs[2]) === 104) {
        trackedArmy.buffs[2] = 89;
        trackedArmy.spireBuffs = [0, 15, 0, 0, 0];
        try { GM_setValue("ELVENAR_TRACKED_ARMY", JSON.stringify(trackedArmy)); } catch(e) {}
    }

    let savedEncounter = null;
    try { savedEncounter = JSON.parse(GM_getValue("ELVENAR_TRACKED_ENCOUNTER", "null")); } catch(e) {}
    // Dọn dẹp ải mẫu hardcode cũ nếu có lưu trong bộ nhớ đệm
    if (savedEncounter && savedEncounter.pSq === 23000 && savedEncounter.eSq === 44892) {
        savedEncounter = null;
        try { GM_setValue("ELVENAR_TRACKED_ENCOUNTER", "null"); } catch(e) {}
    }
    let trackedEncounter = savedEncounter || null;

    let savedBattleBoard = null;
    try { savedBattleBoard = JSON.parse(GM_getValue("ELVENAR_BATTLE_BOARD", "null")); } catch(e) {}
    let battleBoard = savedBattleBoard || { width: 8, height: 9, obstacles: [] };

    const SEEDED_TOURNEY_MAPS = {
        "planks_P31": [[2,1],[2,5],[3,1],[3,2],[4,3],[6,7]],
        "planks_P32": [[1,2],[1,3],[1,5],[1,6],[2,2],[2,6],[5,1],[5,4]],
        "planks_P33": [[1,7],[4,1],[4,2],[5,2],[5,4]],
        "planks_P34": [[1,7],[2,1],[3,0],[3,1],[4,6],[4,7],[5,1],[5,6]],
        "planks_P35": [[1,5],[2,1],[3,1],[3,2],[4,6],[4,7],[5,1],[5,6]],
        "planks_P36": [[1,1],[1,2],[2,2],[5,1],[5,5],[6,1],[6,2]],
        "crystal_P1": [[1,5],[1,6],[2,6],[5,5],[6,5],[6,6]],
        "crystal_P2": [[1,2],[1,5],[2,2],[2,6],[2,7],[3,1],[3,2],[3,7],[4,6],[5,6],[6,5],[6,6]],
        "crystal_P3": [[1,6],[1,7],[2,6],[4,6],[5,1],[5,2],[5,3],[5,6],[6,0],[6,5],[6,6]],
        "crystal_P4": [[2,5],[3,4],[3,5],[4,1],[4,2],[4,5],[4,6],[5,2],[5,6]],
        "crystal_P5": [[1,5],[1,6],[2,1],[2,6],[3,0],[3,1],[4,5],[5,1],[5,6],[5,7],[6,0],[6,1],[6,7]],
        "crystal_P6": [[1,0],[2,0],[2,1],[3,2],[4,2],[5,2],[6,1],[6,2]],
        "crystal_P7": [[1,3],[2,0],[2,1],[2,2],[2,5],[2,6],[2,7],[3,4]],
        "crystal_P8": [[1,1],[1,2],[2,2],[2,5],[3,5],[3,6],[4,2],[4,3],[5,2],[5,5],[6,5],[6,6]],
        "crystal_P9": [[1,5],[1,6],[2,1],[2,6],[3,0],[3,1],[4,2],[4,3],[5,2]],
        "crystal_P10": [[2,1],[2,2],[2,3],[3,0]],
        "crystal_P11": [[1,0],[2,0],[2,1],[3,2],[4,0],[4,5],[5,0],[5,1],[5,6],[5,7],[6,2],[6,7]],
        "crystal_P12": [[1,1],[1,6],[1,7],[2,2],[2,3],[2,6],[3,3],[5,1],[6,1],[6,2]],
        "crystal_P13": [[1,0],[1,5],[1,6],[2,0],[2,1],[2,5],[3,2],[3,5]],
        "crystal_P14": [[1,1],[2,2],[2,3],[3,3],[4,1],[5,2],[5,3],[6,3]],
        "crystal_P15": [[1,4],[2,4],[2,5],[3,6],[4,1],[4,2],[5,1],[6,1]],
        "crystal_P16": [[1,1],[1,2],[1,5],[1,6],[2,1],[2,5],[3,1],[3,5],[4,0],[4,7],[5,0],[5,1],[5,4],[5,5],[5,6],[6,2]],
        "crystal_P17": [[1,2],[1,4],[2,2],[2,4],[2,5],[3,1],[3,2],[3,6],[4,3],[5,0],[5,1],[5,2]],
        "crystal_P18": [[1,1],[1,2],[1,6],[2,2],[2,6],[3,5],[3,6],[4,6],[4,7],[5,1],[5,6],[6,1],[6,2]],
        "crystal_P19": [[1,1],[1,6],[2,2],[2,3],[2,6],[3,3],[3,5],[3,6],[4,2],[5,2],[5,5],[6,1],[6,2],[6,5],[6,6]],
        "crystal_P20": [[2,1],[2,5],[3,1],[3,2],[3,5],[3,6],[4,0],[5,0],[5,1],[6,2]],
        "crystal_P21": [[1,2],[1,5],[1,6],[2,2],[2,5],[3,1],[3,2],[3,5],[4,2],[5,2],[5,5],[5,6],[5,7],[6,1],[6,2],[6,4]],
        "crystal_P22": [[1,5],[1,6],[2,1],[2,6],[3,1],[3,2],[4,2],[4,3],[4,5],[4,6],[5,2],[5,6]],
        "crystal_P23": [[1,3],[1,6],[2,0],[2,1],[2,2],[2,6],[3,5],[3,6],[4,2],[5,2],[6,1],[6,2]],
        "crystal_P24": [[1,2],[1,7],[2,2],[2,4],[2,5],[2,6],[3,1],[3,2],[4,7],[5,4],[5,5],[5,6]],
        "crystal_P25": [[1,4],[2,4],[2,5],[3,6],[4,1],[4,7],[5,2],[5,3],[5,4],[5,5],[5,6],[6,3]],
        "crystal_P26": [[1,1],[2,2],[2,3],[3,3],[4,4],[5,4],[5,5],[6,6]],
        "crystal_P27": [[1,5],[1,6],[2,1],[2,6],[3,0],[3,1],[4,2],[4,3],[4,6],[4,7],[5,2],[5,6]],
        "crystal_P28": [[1,3],[1,4],[2,0],[2,1],[2,2],[2,4],[2,5],[3,6],[4,3],[5,0],[5,1],[5,2]],
        "crystal_P29": [],
        "crystal_P30": [[2,1],[2,5],[3,1],[3,2],[3,4],[3,5],[4,0],[5,0],[5,1],[5,5],[6,2],[6,5],[6,6]],
        "crystal_P31": [[1,5],[2,1],[2,2],[2,3],[2,6],[2,7],[3,0],[3,7],[4,5],[4,6],[5,5],[6,5]],
        "crystal_P32": [[1,1],[1,2],[2,1],[3,1],[4,5],[5,1],[5,2],[5,3],[5,6],[5,7],[6,0],[6,7]],
        "crystal_P33": [[1,7],[2,1],[2,4],[2,5],[2,6],[3,0],[3,1],[5,1],[5,5],[6,0],[6,1],[6,5],[6,6]],
        "crystal_P34": [[1,6],[1,7],[2,1],[2,6],[3,1],[3,2],[5,1],[5,5],[5,6],[5,7],[6,0],[6,1],[6,4]],
        "crystal_P35": [[1,1],[1,2],[1,5],[1,6],[2,1],[2,5],[3,1],[3,5],[4,1],[4,6],[5,2],[5,3],[5,6],[6,3],[6,5],[6,6]],
        "crystal_P37": [[1,2],[2,2],[3,1],[3,2],[4,2],[4,5],[5,2],[5,6],[5,7],[6,1],[6,2],[6,7]]
    };

    let savedTourneyMapCache = null;
    try { savedTourneyMapCache = JSON.parse(GM_getValue("ELVENAR_TOURNAMENT_MAP_CACHE", "{}")); } catch(e) {}
    let tournamentMapCache = (savedTourneyMapCache && typeof savedTourneyMapCache === "object") ? savedTourneyMapCache : {};
    const seedTs = Math.floor(Date.now() / 1000);
    let cacheSanitized = false;
    for (let sk in SEEDED_TOURNEY_MAPS) {
        const seededObs = SEEDED_TOURNEY_MAPS[sk];
        const entry = tournamentMapCache[sk];
        // Làm sạch Cache: nếu chưa có, hoặc không phải mảng, hoặc số lượng vật cản lệch so với chuẩn hạt giống (đặc biệt sửa crystal_P1 bị nhiễm độc 12 vật cản)
        if (!entry || !Array.isArray(entry.obstacles) || entry.obstacles.length !== seededObs.length) {
            tournamentMapCache[sk] = { obstacles: seededObs, ts: seedTs };
            cacheSanitized = true;
        }
    }
    if (cacheSanitized) {
        try { GM_setValue("ELVENAR_TOURNAMENT_MAP_CACHE", JSON.stringify(tournamentMapCache)); } catch(e) {}
    }

    let lastSentText = "";
    let isUpdating = false; // Cờ khóa chống gửi chồng chéo
    let isUpdatingTime = 0; // Thời điểm bắt đầu lock
    let liveStreamDebounce = null; // Debounce timer cho Event-Driven Realtime
    let lastTelegramApiCallTime = 0; // Chống spam Telegram API quá dày đặc
    let lastPinCheckTime = 0; // Đảm bảo tin nhắn luôn luôn được ghim
    let lastSentDataSignature = ""; // Chữ ký dữ liệu lần gửi trước để lọc trùng tuyệt đối
    let lastSuccessfulSyncTime = 0; // Mốc thời gian gửi thành công gần nhất

    function saveStateCache() {
        try {
            GM_setValue("ELVENAR_TRACKED_MIL", JSON.stringify(militaryQueues));
            GM_setValue("ELVENAR_TRACKED_WS", JSON.stringify(workshops));
            GM_setValue("ELVENAR_TRACKED_AWS", JSON.stringify(trackedAWs));
            GM_setValue("ELVENAR_TRACKED_PETS", JSON.stringify(trackedPets));
            GM_setValue("ELVENAR_TRACKED_ARMY", JSON.stringify(trackedArmy));
            GM_setValue("ELVENAR_TRACKED_ENCOUNTER", JSON.stringify(trackedEncounter));
            GM_setValue("ELVENAR_BATTLE_BOARD", JSON.stringify(battleBoard));
        } catch(e) {}
    }

    // =========================================================================
    // 📦 THEO DÕI TÀI NGUYÊN TIÊU CHUẨN (STANDARD GOODS T1, T2, T3) & SỔ CÁI KIẾM/XÀI
    // =========================================================================
    const STANDARD_GOODS_KEYS = [
        "marble", "steel", "planks",       // Tier 1
        "crystal", "scrolls", "silk",      // Tier 2
        "elixir", "magic_dust", "gems"     // Tier 3
    ];

    function formatLocalDate(d = new Date()) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return `${y}-${m}-${day}`;
    }

    // Định nghĩa 1 tuần từ Chủ Nhật (00:00:00) đến tối Thứ Bảy (23:59:59)
    function getSundayOfCurrentWeek(d = new Date()) {
        const date = new Date(d);
        const day = date.getDay(); // 0 = Sunday, 1 = Monday, ..., 6 = Saturday
        date.setDate(date.getDate() - day);
        date.setHours(0, 0, 0, 0);
        return date;
    }

    const LEDGER_SCHEMA_VERSION = 3;
    let resourceLedger = null;
    try {
        resourceLedger = JSON.parse(GM_getValue("ELVENAR_RESOURCE_LEDGER", "null"));
    } catch(e) {}
    if (!resourceLedger || resourceLedger.schemaVersion !== LEDGER_SCHEMA_VERSION) {
        resourceLedger = {
            schemaVersion: LEDGER_SCHEMA_VERSION,
            lastKnownStock: {},
            days: {}
        };
        try { GM_setValue("ELVENAR_RESOURCE_LEDGER", JSON.stringify(resourceLedger)); } catch(e) {}
    }

    let lastCloudLedgerPushTime = 0;
    function syncResourceLedgerToCloud() {
        if (!FIREBASE_DATABASE_URL) return;
        // Debounce chống spam khi game gửi dồn dập: tối đa 1 lần mỗi 8 giây
        if (Date.now() - lastCloudLedgerPushTime < 8000) return;
        lastCloudLedgerPushTime = Date.now();

        const ledgerUrl = FIREBASE_DATABASE_URL.replace('live.json', 'ledger.json');
        GM_xmlhttpRequest({
            method: "PUT",
            url: ledgerUrl,
            headers: { "Content-Type": "application/json" },
            data: JSON.stringify(resourceLedger),
            onload: function(res) {
                console.log("[Firebase Cloud Backup] Đã sao lưu sổ cái 30 ngày lên Google Cloud!");
            },
            onerror: function(err) {}
        });
    }

    function initCloudLedgerSync() {
        if (!FIREBASE_DATABASE_URL) return;
        const ledgerUrl = FIREBASE_DATABASE_URL.replace('live.json', 'ledger.json');
        GM_xmlhttpRequest({
            method: "GET",
            url: `${ledgerUrl}?t=${Date.now()}`,
            onload: function(res) {
                try {
                    const cloudLedger = JSON.parse(res.responseText);
                    if (cloudLedger && cloudLedger.days && Object.keys(cloudLedger.days).length > 0) {
                        let merged = false;
                        if (!resourceLedger.days) resourceLedger.days = {};
                        for (let dayKey in cloudLedger.days) {
                            if (!resourceLedger.days[dayKey]) {
                                resourceLedger.days[dayKey] = cloudLedger.days[dayKey];
                                merged = true;
                            } else {
                                for (let resKey of STANDARD_GOODS_KEYS) {
                                    const localItem = resourceLedger.days[dayKey][resKey] || { earned: 0, spent: 0 };
                                    const cloudItem = cloudLedger.days[dayKey][resKey] || { earned: 0, spent: 0 };
                                    if ((cloudItem.earned + cloudItem.spent) > (localItem.earned + localItem.spent)) {
                                        resourceLedger.days[dayKey][resKey] = cloudItem;
                                        merged = true;
                                    }
                                }
                            }
                        }
                        if (cloudLedger.lastKnownStock && Object.keys(resourceLedger.lastKnownStock || {}).length === 0) {
                            resourceLedger.lastKnownStock = cloudLedger.lastKnownStock;
                            merged = true;
                        }
                        if (merged) {
                            GM_setValue("ELVENAR_RESOURCE_LEDGER", JSON.stringify(resourceLedger));
                            console.log("[Firebase Cloud Backup] Khôi phục thành công lịch sử sổ cái từ Google Cloud!");
                        }
                    }
                } catch(e) {}
            }
        });
    }

    function syncMapToCloud(provKey, obstacles, ts) {
        if (!FIREBASE_DATABASE_URL || !provKey) return;
        try {
            const mapsUrl = FIREBASE_DATABASE_URL.replace('live.json', 'maps.json');
            GM_xmlhttpRequest({
                method: "PATCH",
                url: mapsUrl,
                headers: { "Content-Type": "application/json" },
                data: JSON.stringify({
                    [provKey]: {
                        obstacles: Array.isArray(obstacles) ? obstacles : [],
                        ts: Number(ts) || Math.floor(Date.now() / 1000)
                    }
                }),
                onload: function(res) {
                    console.log(`[CloudMap] Synced ${provKey} to Firebase maps.json (status: ${res.status})`);
                },
                onerror: function(err) {
                    console.warn(`[CloudMap] Error syncing ${provKey} to Cloud:`, err);
                }
            });
        } catch(e) {
            console.warn("[CloudMap] syncMapToCloud exception:", e);
        }
    }

    function initCloudMapsSync() {
        if (!FIREBASE_DATABASE_URL) return;
        try {
            const mapsUrl = FIREBASE_DATABASE_URL.replace('live.json', 'maps.json');
            GM_xmlhttpRequest({
                method: "GET",
                url: `${mapsUrl}?t=${Date.now()}`,
                onload: function(res) {
                    try {
                        let cloudData = null;
                        if (res.status >= 200 && res.status < 300 && res.responseText && res.responseText !== "null") {
                            cloudData = JSON.parse(res.responseText);
                        }
                        let missingKeys = [];
                        for (let sk in SEEDED_TOURNEY_MAPS) {
                            if (!cloudData || !cloudData[sk] || (cloudData[sk].obstacles === undefined && SEEDED_TOURNEY_MAPS[sk].length > 0)) {
                                missingKeys.push(sk);
                            }
                        }
                        if (missingKeys.length > 0 || !cloudData) {
                            console.log(`[CloudMap] Cloud maps missing ${missingKeys.length} seeds. Syncing tournamentMapCache to maps.json...`);
                            GM_xmlhttpRequest({
                                method: "PATCH",
                                url: mapsUrl,
                                headers: { "Content-Type": "application/json" },
                                data: JSON.stringify(tournamentMapCache),
                                onload: function(patchRes) {
                                    console.log(`[CloudMap] Successfully synced seed maps to Firebase (status: ${patchRes.status})`);
                                }
                            });
                        }
                        if (cloudData && typeof cloudData === "object") {
                            let updated = false;
                            for (let ck in cloudData) {
                                if (cloudData[ck]) {
                                    const obs = Array.isArray(cloudData[ck].obstacles) ? cloudData[ck].obstacles : (cloudData[ck].ts ? [] : null);
                                    if (Array.isArray(obs)) {
                                        if (!tournamentMapCache[ck] || !Array.isArray(tournamentMapCache[ck].obstacles) || (cloudData[ck].ts && cloudData[ck].ts > (tournamentMapCache[ck].ts || 0))) {
                                            tournamentMapCache[ck] = { obstacles: obs, ts: cloudData[ck].ts || Math.floor(Date.now() / 1000) };
                                            updated = true;
                                        }
                                    }
                                }
                            }
                            if (updated) {
                                GM_setValue("ELVENAR_TOURNAMENT_MAP_CACHE", JSON.stringify(tournamentMapCache));
                                console.log("[CloudMap] Merged latest cloud maps into local tournamentMapCache");
                            }
                        }
                    } catch(e) {
                        console.warn("[CloudMap] Failed to parse maps.json:", e);
                    }
                },
                onerror: function(err) {
                    console.warn("[CloudMap] Failed to fetch maps.json from Cloud:", err);
                }
            });
        } catch(e) {
            console.warn("[CloudMap] initCloudMapsSync exception:", e);
        }
    }

    function saveResourceLedger() {
        try {
            GM_setValue("ELVENAR_RESOURCE_LEDGER", JSON.stringify(resourceLedger));
            syncResourceLedgerToCloud();
        } catch(e) {}
    }

    function processCityResources(resObj) {
        if (!resObj) return;
        const todayKey = formatLocalDate();
        if (!resourceLedger.days) resourceLedger.days = {};
        if (!resourceLedger.days[todayKey]) resourceLedger.days[todayKey] = {};
        if (!resourceLedger.lastKnownStock) resourceLedger.lastKnownStock = {};

        const todayRecord = resourceLedger.days[todayKey];
        let hasChanges = false;

        for (const key of STANDARD_GOODS_KEYS) {
            if (resObj[key] !== undefined && typeof resObj[key] === 'number') {
                const currentAmount = resObj[key];
                if (!todayRecord[key]) {
                    todayRecord[key] = { earned: 0, spent: 0 };
                }

                if (resourceLedger.lastKnownStock[key] !== undefined) {
                    const prevAmount = resourceLedger.lastKnownStock[key];
                    const delta = currentAmount - prevAmount;
                    if (delta > 0) {
                        todayRecord[key].earned += delta;
                        hasChanges = true;
                    } else if (delta < 0) {
                        todayRecord[key].spent += Math.abs(delta);
                        hasChanges = true;
                    }
                } else {
                    // Thiết lập mốc ban đầu (baseline)
                    hasChanges = true;
                }
                resourceLedger.lastKnownStock[key] = currentAmount;
            }
        }

        // Tự động dọn dẹp các ngày cũ hơn 45 ngày để trọn vẹn cả tháng mà vẫn tiết kiệm dung lượng
        const cutoffDate = new Date();
        cutoffDate.setDate(cutoffDate.getDate() - 45);
        const cutoffStr = formatLocalDate(cutoffDate);
        for (const dStr in resourceLedger.days) {
            if (dStr < cutoffStr) {
                delete resourceLedger.days[dStr];
            }
        }

        if (hasChanges) {
            saveResourceLedger();
            triggerLiveStreamPush();
        }
    }

    function getWeeklyResourceTotals() {
        const sunday = getSundayOfCurrentWeek();
        const saturday = new Date(sunday);
        saturday.setDate(sunday.getDate() + 6);

        const sundayStr = formatLocalDate(sunday);
        const saturdayStr = formatLocalDate(saturday);

        const weekTotals = {};
        for (const key of STANDARD_GOODS_KEYS) {
            weekTotals[key] = { earned: 0, spent: 0 };
        }

        if (resourceLedger && resourceLedger.days) {
            for (const dStr in resourceLedger.days) {
                if (dStr >= sundayStr && dStr <= saturdayStr) {
                    const dayData = resourceLedger.days[dStr];
                    for (const key of STANDARD_GOODS_KEYS) {
                        if (dayData[key]) {
                            weekTotals[key].earned += (dayData[key].earned || 0);
                            weekTotals[key].spent += (dayData[key].spent || 0);
                        }
                    }
                }
            }
        }
        return weekTotals;
    }

    function getMonthlyResourceTotals() {
        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const monthPrefix = `${year}-${month}`; // vd: "2026-11"

        const monthTotals = {};
        for (const key of STANDARD_GOODS_KEYS) {
            monthTotals[key] = { earned: 0, spent: 0 };
        }

        if (resourceLedger && resourceLedger.days) {
            for (const dStr in resourceLedger.days) {
                if (dStr.startsWith(monthPrefix)) {
                    const dayData = resourceLedger.days[dStr];
                    for (const key of STANDARD_GOODS_KEYS) {
                        if (dayData[key]) {
                            monthTotals[key].earned += (dayData[key].earned || 0);
                            monthTotals[key].spent += (dayData[key].spent || 0);
                        }
                    }
                }
            }
        }
        return monthTotals;
    }

    function buildCompactResourceData() {
        const todayKey = formatLocalDate();
        const todayRecord = (resourceLedger.days && resourceLedger.days[todayKey]) || {};
        const weekTotals = getWeeklyResourceTotals();
        const monthTotals = getMonthlyResourceTotals();
        const curStock = resourceLedger.lastKnownStock || {};

        // Mỗi phần tử trong mảng: [currentStock, todayEarn, todaySpent, weekEarn, weekSpent, monthEarn, monthSpent]
        return STANDARD_GOODS_KEYS.map(k => [
            curStock[k] || 0,
            todayRecord[k]?.earned || 0,
            todayRecord[k]?.spent || 0,
            weekTotals[k]?.earned || 0,
            weekTotals[k]?.spent || 0,
            monthTotals[k]?.earned || 0,
            monthTotals[k]?.spent || 0
        ]);
    }

    const troopWeightMap = {
        // Barracks (Elves & Humans)
        "eb_lm": 1, "eb_lr": 1, "eb_ma": 4, "eb_hm": 6, "eb_hr": 6,
        "hb_lm": 1, "hb_lr": 1, "hb_ma": 4, "hb_hm": 6, "hb_hr": 6,
        // Training Grounds
        "tg_lm": 1, "tg_lr": 2, "tg_ma": 3, "tg_hm": 2, "tg_hr": 2,
        // Mercenary Camp (CHÍNH XÁC 100% THEO GAME BALANCING DATA)
        "mc_lm": 2, // Drone Rider (weight = 2)
        "mc_lr": 1, // Ranger (weight = 1)
        "mc_ma": 3, // Blossom Mage (weight = 3)
        "mc_hm": 6, // Vallorian Guard (weight = 6)
        "mc_hr": 4  // Frog Prince (weight = 4)
    };

    const troopKeyMap = {
        "eb_lm": "barracks_lm", "hb_lm": "barracks_lm",
        "eb_lr": "barracks_lr", "hb_lr": "barracks_lr",
        "eb_ma": "barracks_ma", "hb_ma": "barracks_ma",
        "eb_hm": "barracks_hm", "hb_hm": "barracks_hm",
        "eb_hr": "barracks_hr", "hb_hr": "barracks_hr",
        "tg_lm": "training_lm",
        "tg_lr": "training_lr",
        "tg_ma": "training_ma",
        "tg_hm": "training_hm",
        "tg_hr": "training_hr",
        "mc_lm": "mercenary_lm",
        "mc_lr": "mercenary_lr",
        "mc_ma": "mercenary_ma",
        "mc_hm": "mercenary_hm",
        "mc_hr": "mercenary_hr"
    };

    function formatSquadCount(numSquads) {
        if (numSquads >= 100) return Math.floor(numSquads);
        return Math.round(numSquads * 10) / 10;
    }

    function recalculateSquads() {
        if (!trackedArmy || !trackedArmy.raw) return;
        const clusterSize = Number(trackedArmy.squadSize) || 0;
        if (clusterSize <= 0) return;
        if (!trackedArmy.squads) trackedArmy.squads = {};
        for (let cellKey in trackedArmy.raw) {
            const rawCount = trackedArmy.raw[cellKey];
            if (rawCount !== undefined && rawCount !== null) {
                let weight = 1;
                for (let pre in troopKeyMap) {
                    if (troopKeyMap[pre] === cellKey) {
                        weight = troopWeightMap[pre] || 1;
                        break;
                    }
                }
                const numSquads = (rawCount * weight) / clusterSize;
                trackedArmy.squads[cellKey] = formatSquadCount(numSquads);
            }
        }
    }

    function updateSingleSquad(sq, clusterSize) {
        if (!sq || !sq.unitTypeId) return false;
        const prefix = sq.unitTypeId.substring(0, 5);
        const cellKey = troopKeyMap[prefix];
        if (!cellKey) return false;
        const weight = troopWeightMap[prefix] || 1;
        const size = sq.size !== undefined ? sq.size : (sq.amount !== undefined ? sq.amount : (sq.count !== undefined ? sq.count : 0));
        const effectiveCluster = Number(clusterSize) || Number(trackedArmy && trackedArmy.squadSize) || 0;
        if (!trackedArmy) trackedArmy = { squadSize: effectiveCluster, squads: {}, raw: {}, tiers: {} };
        if (!trackedArmy.raw) trackedArmy.raw = {};
        if (!trackedArmy.squads) trackedArmy.squads = {};
        if (!trackedArmy.tiers) trackedArmy.tiers = {};
        const tierMatch = String(sq.unitTypeId).match(/_(\d+)$/);
        if (tierMatch) trackedArmy.tiers[cellKey] = Number(tierMatch[1]);
        if (effectiveCluster > 0) trackedArmy.squadSize = effectiveCluster;
        trackedArmy.raw[cellKey] = size;
        if (effectiveCluster > 0) {
            const numSquads = (size * weight) / effectiveCluster;
            trackedArmy.squads[cellKey] = formatSquadCount(numSquads);
        }
        return true;
    }

    // Cập nhật kho quân dự bị trực tiếp từ CityResourceVO (Kho tài nguyên thực của người chơi)
    function processTroopResources(resources) {
        if (!resources) return false;
        const clusterSize = Number(trackedArmy && trackedArmy.squadSize) || 0;
        if (!trackedArmy) trackedArmy = { squadSize: clusterSize, squads: {}, raw: {}, tiers: {} };
        if (!trackedArmy.raw) trackedArmy.raw = {};
        if (!trackedArmy.squads) trackedArmy.squads = {};

        let changed = false;
        for (let prefix in troopKeyMap) {
            if (resources[prefix] !== undefined && resources[prefix] !== null) {
                const rawCount = Number(resources[prefix]) || 0;
                const cellKey = troopKeyMap[prefix];
                if (trackedArmy.raw[cellKey] !== rawCount) {
                    trackedArmy.raw[cellKey] = rawCount;
                    changed = true;
                }
                if (clusterSize > 0) {
                    const weight = troopWeightMap[prefix] || 1;
                    const numSquads = (rawCount * weight) / clusterSize;
                    const squadFormatted = formatSquadCount(numSquads);
                    if (trackedArmy.squads[cellKey] !== squadFormatted) {
                        trackedArmy.squads[cellKey] = squadFormatted;
                        changed = true;
                    }
                }
            }
        }
        if (changed) {
            GM_setValue("ELVENAR_TRACKED_ARMY", JSON.stringify(trackedArmy));
        }
        return changed;
    }

    // Tự động tính toán lại số squad chuẩn xác nếu đã có bộ đệm raw từ trước
    try {
        if (trackedArmy && trackedArmy.raw && Object.keys(trackedArmy.raw).length > 0) {
            recalculateSquads();
        }
    } catch(e) {}

    // --- 1.F HỖ TRỢ TRÍCH XUẤT BẢN ĐỒ & VẬT CẢN (BATTLEFIELD MAP & OBSTACLES PIPELINE) ---
    function extractObstaclesFromMap(bMap) {
        if (!bMap) return [];
        if (bMap.map && (bMap.map.tiles || bMap.map.width)) {
            bMap = bMap.map;
        }
        const tiles = bMap.tiles || (Array.isArray(bMap) ? bMap : null);
        if (!tiles || !Array.isArray(tiles) || tiles.length === 0) return [];

        const obstacles = [];
        const seen = new Set();

        function addObs(x, y) {
            const ox = Number(x);
            const oy = Number(y);
            if (!isNaN(ox) && !isNaN(oy) && ox >= 0 && ox < 8 && oy >= 0 && oy < 9) {
                const key = ox + "," + oy;
                if (!seen.has(key)) {
                    seen.add(key);
                    obstacles.push([ox, oy]);
                }
            }
        }

        function isObstacleCell(cell) {
            if (!cell) return false;
            if (typeof cell === "string") {
                const s = cell.toLowerCase();
                return s.includes("obstacle") || s.includes("blocked") || s.includes("barrier");
            }
            if (typeof cell === "object") {
                const typeId = String(cell.typeId || cell.type || "").toLowerCase();
                const cost = Number(cell.movementCosts !== undefined ? cell.movementCosts : (cell.cost !== undefined ? cell.cost : 0));
                return typeId === "obstacle" || 
                       typeId.includes("obstacle") || 
                       typeId.includes("blocked") || 
                       cost > 1000 || 
                       cell.isObstacle === true || 
                       cell.blocked === true || 
                       cell.passable === false || 
                       cell.walkable === false;
            }
            return false;
        }

        if (Array.isArray(tiles[0])) {
            for (let x = 0; x < tiles.length; x++) {
                const col = tiles[x];
                if (!Array.isArray(col)) continue;
                for (let y = 0; y < col.length; y++) {
                    const cell = col[y];
                    if (isObstacleCell(cell)) {
                        const pos = cell && typeof cell === "object" ? (cell.pos || cell.position || cell) : null;
                        const ox = (pos && pos.x !== undefined && !isNaN(pos.x)) ? Number(pos.x) : x;
                        const oy = (pos && pos.y !== undefined && !isNaN(pos.y)) ? Number(pos.y) : y;
                        addObs(ox, oy);
                    }
                }
            }
        } else {
            for (let i = 0; i < tiles.length; i++) {
                const cell = tiles[i];
                if (isObstacleCell(cell)) {
                    if (cell && typeof cell === "object") {
                        const pos = cell.pos || cell.position || cell;
                        if (pos.x !== undefined && pos.y !== undefined) {
                            addObs(pos.x, pos.y);
                            continue;
                        }
                    }
                    const h = Number(bMap.height) || 9;
                    const ox = Math.floor(i / h);
                    const oy = i % h;
                    addObs(ox, oy);
                }
            }
        }

        obstacles.sort((a, b) => (a[0] !== b[0] ? a[0] - b[0] : a[1] - b[1]));
        return obstacles;
    }

    function areWavesCompatible(prevWaves, newWaves) {
        if (!Array.isArray(prevWaves) || !Array.isArray(newWaves) || prevWaves.length === 0 || newWaves.length === 0) return false;
        if (JSON.stringify(prevWaves) === JSON.stringify(newWaves)) return true;
        if (prevWaves.length === newWaves.length) {
            const w0Prev = [...(prevWaves[0] || [])].sort().join(",");
            const w0New = [...(newWaves[0] || [])].sort().join(",");
            if (w0Prev && w0Prev === w0New) return true;
        }
        return false;
    }

    // Nhận diện chính xác 100% số Tỉnh Tournament P (Piecewise formula - bất biến qua 6 Sao: Star 1..6 có cùng 1 bản đồ địa hình)
    function getTournamentK(r) {
        if (r < 0.92) return Math.max(1, Math.round(r / 0.12595));
        if (r < 1.08) return 7 + Math.round((r - 0.8816) / 0.0882);
        if (r < 1.39) return 9 + Math.round((r - 1.0580) / 0.0454);
        if (r < 2.03) return 16 + Math.round((r - 1.3757) / 0.0360);
        return 35 + Math.max(0, Math.round((r - 2.0338) / 0.010));
    }

    function getTournamentProvinceKey(goodId, pSq, eSq, basePts, explicitNumber) {
        const good = String(goodId || "tourney").toLowerCase();
        if (explicitNumber && Number(explicitNumber) > 0) {
            return `${good}_P${Number(explicitNumber)}`;
        }
        const p = Number(pSq) || 0;
        const e = Number(eSq) || 0;
        if (p <= 0 || e <= 0) return "";
        const r = e / p;
        const k = getTournamentK(r);
        const pts = Number(basePts) || 30;
        const star = (pts >= 30 && pts <= 60) ? Math.max(1, Math.min(6, Math.round((pts - 24) / 6))) : 1;
        const provNum = Math.max(1, k - (star - 1));
        return `${good}_P${provNum}`;
    }

    // --- 2. BẮT GÓI TIN GAME ---
    function handleData(data) {
        try {
            const now = Math.floor(Date.now() / 1000);
            let hasFullResources = false;
            try {
                const dataStr = JSON.stringify(data);
                hasFullResources = dataStr.includes("CityResourcesService") && dataStr.includes("getResources");
            } catch(e) {}

            function walk(node) {
                if (!node || typeof node !== 'object') return;

                // Tự động nhận diện Player ID của chính mình
                if (node.__class__ === "CityUserDataVO" && node.player_id) {
                    myPlayerId = String(node.player_id);
                    GM_setValue("ELVENAR_MY_PLAYER_ID", myPlayerId);
                }

                // Chặn toàn bộ dữ liệu Kỳ quan của người chơi khác (Sniping monitor, hội viên, hàng xóm)
                if (node.__class__ === "OtherPlayerAncientWondersVO") return;
                if (node.player_id && myPlayerId && String(node.player_id) !== String(myPlayerId)) return;

                // A. Military Queues
                if (node.__class__ === "ProductionQueueVO" || (node.id && militaryQueues[node.id])) {
                    const qId = node.id;
                    if (militaryQueues[qId]) {
                        const q = militaryQueues[qId];
                        q.slots = node.slots || [];
                        q.maxSlots = node.maxSlots || 5;

                        if (q.slots.length > 0) {
                            const firstRem = Number(q.slots[0].remainingTime) || 0;
                            const totalRem = q.slots.reduce((sum, slot) => sum + (Number(slot.remainingTime) || 0), 0);
                            q.firstSlotFinishTime = now + firstRem;
                            q.totalFinishTime = now + totalRem;
                        } else {
                            q.firstSlotFinishTime = 0;
                            q.totalFinishTime = 0;
                        }
                    }
                }

                // B. City Map Entities (Workshops, AWs, Pets)
                const uid = String(node.id || node.entity_id || "");
                const entId = String(node.cityentity_id || node.cityEntityId || "").toLowerCase();
                const isWorkshop = entId.includes("workshop") || (uid && !!workshops[uid]);
                const isAW = Object.keys(trackedAWs).some(k => entId.includes(k) || (trackedAWs[k].uid && trackedAWs[k].uid === uid));
                const isPet = entId.includes("bear_brown") || entId.includes("shellux") || (uid && !!petEntityMap[uid]);

                if (node.__class__ === "CityMapEntityVO" || entId || isWorkshop || isAW || isPet) {
                    if (entId.includes("bear_brown")) {
                        petEntityMap[uid] = "unit_production_pickup_boost";
                    }
                    if (entId.includes("shellux")) {
                        petEntityMap[uid] = "training_speed_bonus";
                    }

                    if (isWorkshop) {
                        const match = entId.match(/\d+/);
                        const level = Number(node.level) || (match ? parseInt(match[0], 10) : (workshops[uid]?.level || 0));

                        let status = workshops[uid]?.status || "Idle";
                        let finishTime = workshops[uid]?.finishTime || 0;

                        if (node.state) {
                            const stateClass = node.state.__class__ || "";
                            if (stateClass.includes("ProducingVO")) {
                                status = "Producing";
                                const remain = Number(node.state.next_state_transition_in || node.state.remainingTime || 0);
                                finishTime = now + remain;
                            } else if (stateClass.includes("StateFinishedVO") || stateClass.includes("ProductionFinishedVO")) {
                                status = "Ready";
                                finishTime = 0;
                                const pastSeconds = Math.abs(Number(node.state.next_state_transition_in || 0));
                                if (pastSeconds > 0 && wsStoppedSince === 0) {
                                    wsStoppedSince = now - pastSeconds;
                                    GM_setValue("ELVENAR_WS_STOPPED_SINCE", wsStoppedSince);
                                }
                            } else if (stateClass.includes("IdleVO")) {
                                status = "Idle";
                                finishTime = 0;
                            }
                        }

                        workshops[uid] = { id: uid, level: level, status: status, finishTime: finishTime };
                    }

                    for (let awKey in trackedAWs) {
                        const aw = trackedAWs[awKey];
                        if (entId.includes(awKey) || (aw.uid && aw.uid === uid)) {
                            aw.level = node.level || aw.level;
                            if (uid) aw.uid = uid;

                            const stateClass = (node.state && node.state.__class__) ? node.state.__class__ : "";

                            if (stateClass.includes("ProducingVO")) {
                                aw.status = "Producing";
                                const remain = Number(node.state.next_state_transition_in || node.state.remainingTime || 0);
                                aw.finishTime = now + remain;
                            } else if (stateClass.includes("ProductionFinishedVO") || stateClass.includes("StateFinishedVO")) {
                                aw.status = "Ready";
                                aw.finishTime = 0;
                            } else if (stateClass.includes("UpgradingVO")) {
                                aw.status = "Upgrading";
                                const remain = Number(node.state.next_state_transition_in || 0);
                                aw.finishTime = now + remain;
                            } else if (stateClass.includes("IdleVO")) {
                                aw.status = "Idle";
                                aw.finishTime = 0;
                            }
                        }
                    }
                }

                // C. Spell Effects (Pet Food & Power of Provision)
                if ((node.__class__ === "EffectVO" || node.actionId) && node.type === "spell") {
                    const actId = String(node.actionId || "");
                    const ownerId = String(node.ownerId || "");
                    const targetKey = trackedPets[actId] ? actId : (petEntityMap[ownerId] || null);

                    if (targetKey && trackedPets[targetKey]) {
                        const rem = Number(node.remainingTime) || 0;
                        if (rem > 0) {
                            trackedPets[targetKey].finishTime = now + rem;
                        }
                    }

                    // Power of Provision cho Workshops (CHỈ nhận actionId: supply_production_boost_spell, hỗ trợ dồn spell không giới hạn)
                    if (actId === "supply_production_boost_spell") {
                        const rem = Number(node.remainingTime) || 0;
                        if (rem > 0) {
                            provisionSpellFinishTime = now + rem;
                            GM_setValue("ELVENAR_PROVISION_SPELL_FINISH", provisionSpellFinishTime);
                        }
                    }
                }

                // D. Bắt dữ liệu kho Hàng Hóa Tiêu Chuẩn & Toàn Bộ 15 Đơn Vị Quân Dự Bị (Kho thực của người chơi)
                if (node.__class__ === "CityResourceVO" && node.resources && Object.keys(node.resources).length >= 10 && node.resources.money !== undefined && node.resources.marble !== undefined) {
                    processCityResources(node.resources);
                    if (processTroopResources(node.resources)) {
                        triggerLiveStreamPush();
                    }
                }

                // Tự động bắt Squad Size thực tế từ EffectsService (EffectSourceVO: squadSize)
                if (node.__class__ === "EffectSourceVO" && node.name === "squadSize" && Number(node.value) > 0) {
                    const newSqSize = Number(node.value);
                    if (!trackedArmy) trackedArmy = { squadSize: newSqSize, squads: {}, raw: {}, tiers: {} };
                    if (trackedArmy.squadSize !== newSqSize) {
                        trackedArmy.squadSize = newSqSize;
                        recalculateSquads();
                        GM_setValue("ELVENAR_TRACKED_ARMY", JSON.stringify(trackedArmy));
                        triggerLiveStreamPush();
                    }
                }

                // Tự động nhận diện trọng lượng quân lính trực tiếp từ hệ thống balancing của game
                if (node.__class__ === "BattleUnitTypeVO" && (node.unitTypeId || node.baseName) && node.unitWeight) {
                    const prefix = (node.baseName || node.unitTypeId || "").substring(0, 5);
                    if (troopWeightMap[prefix] !== undefined) {
                        troopWeightMap[prefix] = Number(node.unitWeight);
                    }
                }

                // E. Bắt dữ liệu Quân Đội & Quân Số Dự Bị (CHỈ nhận từ cấu trúc ArmyDetailsVO đầy đủ của người chơi)
                const isArmyDetails = (node.__class__ === "ArmyDetailsVO") || 
                                      (node.battleClusterSize && Array.isArray(node.unitSquads) && node.unitSquads.length >= 10) ||
                                      (node.army_details && Array.isArray(node.army_details.unitSquads) && node.army_details.unitSquads.length >= 10);

                if (isArmyDetails) {
                    const armyObj = node.army_details || node;
                    const clusterSize = Number(armyObj.battleClusterSize) || Number(trackedArmy && trackedArmy.squadSize) || 0;
                    const unitSquads = armyObj.unitSquads || [];
                    if (Array.isArray(unitSquads) && unitSquads.length >= 10) {
                        if (!trackedArmy) trackedArmy = { squadSize: clusterSize, squads: {}, raw: {}, tiers: {} };
                        if (!trackedArmy.tiers) trackedArmy.tiers = {};
                        if (Array.isArray(armyObj.availableUnitTypeIds)) {
                            armyObj.availableUnitTypeIds.forEach(uid => {
                                const pre = String(uid).substring(0, 5);
                                const ck = troopKeyMap[pre];
                                const m = String(uid).match(/_(\d+)$/);
                                if (ck && m) trackedArmy.tiers[ck] = Number(m[1]);
                            });
                        }
                        let changed = false;
                        if (clusterSize > 0 && trackedArmy.squadSize !== clusterSize) {
                            trackedArmy.squadSize = clusterSize;
                            recalculateSquads();
                            changed = true;
                        }
                        unitSquads.forEach(sq => {
                            if (updateSingleSquad(sq, clusterSize)) changed = true;
                        });
                        if (changed) {
                            GM_setValue("ELVENAR_TRACKED_ARMY", JSON.stringify(trackedArmy));
                            triggerLiveStreamPush();
                        }
                    }
                }

                // F. Giao dịch tăng/giảm lính tức thời (Dự phòng trường hợp gói tin không kèm CityResourcesService)
                const reqClass = node.requestClass || node.service;
                const reqMethod = node.requestMethod || node.method;
                if (reqClass === "ArmyService" && reqMethod === "addUnit" && node.responseData) {
                    if (!hasFullResources) {
                        const res = node.responseData;
                        const uId = res.unitTypeId || "";
                        const delta = Number(res.size) || 0;
                        const prefix = uId.substring(0, 5);
                        const cellKey = troopKeyMap[prefix];
                        if (cellKey && delta !== 0) {
                            const clusterSize = Number(trackedArmy && trackedArmy.squadSize) || 0;
                            if (!trackedArmy) trackedArmy = { squadSize: clusterSize, squads: {}, raw: {}, tiers: {} };
                            if (!trackedArmy.raw) trackedArmy.raw = {};
                            if (!trackedArmy.squads) trackedArmy.squads = {};
                            const oldRaw = trackedArmy.raw[cellKey] || 0;
                            const newRaw = Math.max(0, oldRaw + delta);
                            trackedArmy.raw[cellKey] = newRaw;
                            if (clusterSize > 0) {
                                const weight = troopWeightMap[prefix] || 1;
                                const numSquads = (newRaw * weight) / clusterSize;
                                trackedArmy.squads[cellKey] = formatSquadCount(numSquads);
                            }
                            GM_setValue("ELVENAR_TRACKED_ARMY", JSON.stringify(trackedArmy));
                            triggerLiveStreamPush();
                        }
                    }
                }

                // G. Bắt đội hình Quái khi mở ải Tournament / Province / Spire (Hỗ trợ 1-3 Waves cho Auto-Battle Advisor)
                if (Array.isArray(node.encounters) && node.encounters.length > 0) {
                    const activeEnc = node.encounters.find(e => e && Array.isArray(e.enemyWaves) && e.enemyWaves.length > 0 && !e.completed && !e.isCompleted) ||
                                      node.encounters.find(e => e && Array.isArray(e.enemyWaves) && e.enemyWaves.length > 0);
                    if (activeEnc && Array.isArray(activeEnc.enemyWaves) && activeEnc.enemyWaves.length > 0) {
                        const waves = activeEnc.enemyWaves.map(w => (w.army || []).map(u => u.unitTypeId || "")).filter(w => w.length > 0);
                        if (waves.length > 0) {
                            const pSqVal = Number(node.playerSquadSize) || (trackedArmy && trackedArmy.squadSize) || 0;
                            const eSqVal = Number(activeEnc.enemyWaves[0].squadSize) || 0;
                            const provKey = node.good_id ? getTournamentProvinceKey(node.good_id, pSqVal, eSqVal, node.baseTournamentPointsAmount, node.provinceNumber || node.number) : "";
                            let preservedObstacles = null;
                            if (provKey) {
                                if (trackedEncounter && trackedEncounter.provKey === provKey && Array.isArray(trackedEncounter.obstacles)) {
                                    preservedObstacles = trackedEncounter.obstacles;
                                } else if (tournamentMapCache[provKey] && Array.isArray(tournamentMapCache[provKey].obstacles)) {
                                    if ((now - (Number(tournamentMapCache[provKey].ts) || 0)) < 90 * 86400) {
                                        preservedObstacles = tournamentMapCache[provKey].obstacles;
                                    }
                                }
                            } else {
                                if (trackedEncounter && Array.isArray(trackedEncounter.obstacles) && areWavesCompatible(trackedEncounter.waves, waves)) {
                                    preservedObstacles = trackedEncounter.obstacles;
                                }
                            }
                            trackedEncounter = {
                                ts: now,
                                src: node.good_id ? "tournament" : (waves.length > 1 ? "spire" : "province"),
                                good: node.good_id || "",
                                provKey: provKey,
                                pSq: pSqVal,
                                eSq: eSqVal,
                                waves: waves,
                                obstacles: preservedObstacles,
                                lastResult: trackedEncounter ? trackedEncounter.lastResult : null
                            };
                            activeEnc._processedByParent = true;
                            GM_setValue("ELVENAR_TRACKED_ENCOUNTER", JSON.stringify(trackedEncounter));
                            triggerLiveStreamPush();
                        }
                    }
                } else if (Array.isArray(node.enemyWaves) && node.enemyWaves.length > 0 && !node._processedByParent) {
                    const waves = node.enemyWaves.map(w => (w.army || []).map(u => u.unitTypeId || "")).filter(w => w.length > 0);
                    if (waves.length > 0) {
                        const clsName = String(node.__class__ || "").toLowerCase();
                        const goodVal = node.good_id || (trackedEncounter && trackedEncounter.good) || "";
                        const pSqVal = Number(node.playerSquadSize) || (trackedEncounter && trackedEncounter.pSq) || (trackedArmy && trackedArmy.squadSize) || 0;
                        const eSqVal = Number(node.enemyWaves[0].squadSize) || 0;
                        const provKey = goodVal ? getTournamentProvinceKey(goodVal, pSqVal, eSqVal, node.baseTournamentPointsAmount, node.provinceNumber || node.number) : ((trackedEncounter && trackedEncounter.provKey) || "");
                        let preservedObstacles = null;
                        if (provKey) {
                            if (trackedEncounter && trackedEncounter.provKey === provKey && Array.isArray(trackedEncounter.obstacles)) {
                                preservedObstacles = trackedEncounter.obstacles;
                            } else if (tournamentMapCache[provKey] && Array.isArray(tournamentMapCache[provKey].obstacles)) {
                                if ((now - (Number(tournamentMapCache[provKey].ts) || 0)) < 90 * 86400) {
                                    preservedObstacles = tournamentMapCache[provKey].obstacles;
                                }
                            }
                        } else {
                            if (trackedEncounter && Array.isArray(trackedEncounter.obstacles) && areWavesCompatible(trackedEncounter.waves, waves)) {
                                preservedObstacles = trackedEncounter.obstacles;
                            }
                        }
                        trackedEncounter = {
                            ts: now,
                            src: (clsName.includes("spire") || waves.length > 1) ? "spire" : ((trackedEncounter && trackedEncounter.src) || "encounter"),
                            good: goodVal,
                            provKey: provKey,
                            pSq: pSqVal,
                            eSq: eSqVal,
                            waves: waves,
                            obstacles: preservedObstacles,
                            lastResult: trackedEncounter ? trackedEncounter.lastResult : null
                        };
                        GM_setValue("ELVENAR_TRACKED_ENCOUNTER", JSON.stringify(trackedEncounter));
                        triggerLiveStreamPush();
                    }
                }

                // G.2 Bắt Tọa Độ Chướng Ngại Vật (Obstacles) & Bàn Cờ Lục Giác khi mở trận Đánh Tay (BattlefieldService / BattleService / SpireBattleService)
                let mapCandidate = null;
                if (node.__class__ === "BattleRealmVO" && node.map) {
                    mapCandidate = node.map;
                } else if (node.__class__ === "BattleMapVO" && (node.tiles || node.width)) {
                    mapCandidate = node;
                } else if ((node.requestClass === "BattlefieldService" || node.requestClass === "BattleService" || node.requestClass === "SpireBattleService") &&
                           (node.requestMethod === "start" || node.requestMethod === "getBattle") && node.responseData && node.responseData.map) {
                    mapCandidate = node.responseData.map;
                } else if (node.map && Array.isArray(node.map.tiles)) {
                    mapCandidate = node.map;
                } else if (Array.isArray(node.tiles) && Array.isArray(node.tiles[0])) {
                    mapCandidate = node;
                }

                let extractedObs = [];
                if (mapCandidate) {
                    extractedObs = extractObstaclesFromMap(mapCandidate);
                }

                // Fallback dự phòng cho các gói tin phi chuẩn (loại bỏ hoàn toàn u.teamFlag === -1 để không ghi nhận nhầm quân địch)
                if (extractedObs.length === 0) {
                    const directObsKeys = ["obstacles", "blockedFields", "blockedPositions", "barriers", "unwalkableFields"];
                    const gridBoardKeys = ["board", "fields", "cells", "terrain", "hexes"];
                    for (let ok of directObsKeys) {
                        if (Array.isArray(node[ok]) && node[ok].length > 0) {
                            node[ok].forEach(item => {
                                if (item && typeof item === "object") {
                                    const pos = item.pos || item.position || item;
                                    const ox = Number(pos.x !== undefined ? pos.x : 0);
                                    const oy = Number(pos.y !== undefined ? pos.y : 0);
                                    if (!isNaN(ox) && !isNaN(oy) && ox >= 0 && ox < 8 && oy >= 0 && oy < 9 && (pos.x !== undefined || pos.y !== undefined)) {
                                        extractedObs.push([ox, oy]);
                                    }
                                }
                            });
                        }
                    }
                    for (let gk of gridBoardKeys) {
                        if (Array.isArray(node[gk]) && node[gk].length > 0) {
                            node[gk].forEach(item => {
                                if (item && typeof item === "object") {
                                    const isBlocked = Boolean(item.isObstacle || item.obstacle || item.blocked || item.isBlocked || item.walkable === false || item.passable === false || String(item.type || "").toLowerCase().includes("obstacle") || String(item.type || "").toLowerCase().includes("blocked"));
                                    if (isBlocked) {
                                        const pos = item.pos || item.position || item;
                                        const ox = Number(pos.x !== undefined ? pos.x : 0);
                                        const oy = Number(pos.y !== undefined ? pos.y : 0);
                                        if (!isNaN(ox) && !isNaN(oy) && ox >= 0 && ox < 8 && oy >= 0 && oy < 9) {
                                            extractedObs.push([ox, oy]);
                                        }
                                    }
                                }
                            });
                        }
                    }
                }

                if (mapCandidate || extractedObs.length > 0) {
                    const seenObs = new Set();
                    const uniqueObs = [];
                    extractedObs.forEach(pair => {
                        const k = pair[0] + "," + pair[1];
                        if (!seenObs.has(k)) {
                            seenObs.add(k);
                            uniqueObs.push([pair[0], pair[1]]);
                        }
                    });
                    uniqueObs.sort((a, b) => (a[0] !== b[0] ? a[0] - b[0] : a[1] - b[1]));

                    battleBoard.width = (mapCandidate && Number(mapCandidate.width)) || 8;
                    battleBoard.height = (mapCandidate && Number(mapCandidate.height)) || 9;
                    battleBoard.obstacles = uniqueObs;
                    battleBoard.ts = now;
                    GM_setValue("ELVENAR_BATTLE_BOARD", JSON.stringify(battleBoard));

                    if (!trackedEncounter) {
                        trackedEncounter = { ts: now, src: "tournament", good: "", provKey: "", pSq: 0, eSq: 0, waves: [], obstacles: uniqueObs, lastResult: null };
                    } else {
                        trackedEncounter.obstacles = uniqueObs;
                        trackedEncounter.ts = now;
                        if (trackedEncounter.provKey) {
                            tournamentMapCache[trackedEncounter.provKey] = { obstacles: uniqueObs, ts: now };
                            syncMapToCloud(trackedEncounter.provKey, uniqueObs, now);
                            for (let mk in tournamentMapCache) {
                                if (!tournamentMapCache[mk] || (now - (Number(tournamentMapCache[mk].ts) || 0)) > 90 * 86400) {
                                    delete tournamentMapCache[mk];
                                }
                            }
                            GM_setValue("ELVENAR_TOURNAMENT_MAP_CACHE", JSON.stringify(tournamentMapCache));
                        }
                    }
                    GM_setValue("ELVENAR_TRACKED_ENCOUNTER", JSON.stringify(trackedEncounter));
                    triggerLiveStreamPush();
                }

                // H. Bắt danh sách Buff Quân Sự đang kích hoạt trong Thành Phố (EffectsService.update)
                if (node.requestClass === "EffectsService" && node.requestMethod === "update" && Array.isArray(node.responseData)) {
                    const awAtkScale = [0, 5, 7.5, 10, 12.5, 15, 18, 20, 21.5, 23, 25, 28, 30, 31.5, 33, 35, 37.5, 38.5, 39, 40, 40.5, 41.5, 42, 42.5, 43, 43.5, 44, 44.5, 45, 45.5, 46, 47, 47.5, 48, 48.5, 50, 60];
                    const awHpScale  = [0, 3, 5, 7, 9, 11, 13, 14, 15, 16.5, 18, 20.5, 21.5, 23, 24, 25, 27, 27.5, 28, 28.5, 29, 30, 30.3, 30.6, 30.9, 31.2, 31.8, 32.1, 32.4, 32.7, 33, 33.5, 34, 34.5, 35, 36, 40];
                    let hpPct = 0, lmPct = 0, lrPct = 0, maPct = 0, hmPct = 0, hrPct = 0;
                    let spireLmPct = 0, spireLrPct = 0, spireMaPct = 0, spireHmPct = 0, spireHrPct = 0;
                    node.responseData.forEach(ef => {
                        if (!ef) return;
                        const cid = Number(ef.confId) || 0;
                        const lvl = Math.min(36, Math.max(0, Number(ef.level) || 0));
                        const stg = Math.max(0, Number(ef.stage) || 0);
                        const isSpireEffect = (ef.owner === "spire" || ef.type === "spire" || (cid >= 711 && cid <= 715));

                        if (isSpireEffect) {
                            // Spire-Only Military Buffs (Guild Spire Perks)
                            if (cid === 711) spireLmPct += 15;
                            else if (cid === 712) spireLrPct += 15;
                            else if (cid === 713) spireMaPct += 15;
                            else if (cid === 714) spireHmPct += 15;
                            else if (cid === 715) spireHrPct += 15;
                            return;
                        }

                        // City / Global Military Buffs (Active in All Battles: Tournament, Spire, Province)
                        if (cid === 2045) hpPct += (awHpScale[lvl] || 0); // Martial Monastery / Sanctuary
                        else if (cid === 5019) hpPct += 50; // Dwarven Armorer
                        else if (cid === 5002) hpPct += 25; // Unleashed Unit Upgrade
                        else if (cid === 5016) { // Fire Phoenix Pet Effect (+5% per stage)
                            const phx = stg > 0 ? (stg * 5) : 50;
                            lmPct += phx; lrPct += phx; maPct += phx; hmPct += phx; hrPct += phx;
                        }
                        else if (cid === 2123) lmPct += (awAtkScale[lvl] || 0); // Victory Springs (LM)
                        else if (cid === 2043) lrPct += (awAtkScale[lvl] || 0); // Needles of the Tempest (LR)
                        else if (cid === 2103) maPct += (awAtkScale[lvl] || 0); // Dragon Abbey (MA)
                        else if (cid === 2082) hmPct += (awAtkScale[lvl] || 0); // Heroes' Forge (HM)
                        else if (cid === 2112) hrPct += (awAtkScale[lvl] || 0); // Temple of the Toads (HR)
                        else if (cid === 5001) maPct += 50; // Magnificent Mage Multiplier
                        else if (cid === 5003) lrPct += 50; // Enlightened Light Range
                        else if (cid === 5029) lmPct += 75;
                        else if (cid === 5030) hmPct += 75;
                        else if (cid === 5031) hrPct += 50;
                        else if (cid === 5079) hmPct += 50;
                    });
                    if (!trackedArmy) trackedArmy = { squadSize: 0, squads: {}, raw: {}, tiers: {} };
                    trackedArmy.buffs = [
                        Math.round(hpPct * 10) / 10,
                        Math.round(lmPct * 10) / 10,
                        Math.round(lrPct * 10) / 10,
                        Math.round(maPct * 10) / 10,
                        Math.round(hmPct * 10) / 10,
                        Math.round(hrPct * 10) / 10
                    ];
                    trackedArmy.spireBuffs = [
                        Math.round(spireLmPct * 10) / 10,
                        Math.round(spireLrPct * 10) / 10,
                        Math.round(spireMaPct * 10) / 10,
                        Math.round(spireHmPct * 10) / 10,
                        Math.round(spireHrPct * 10) / 10
                    ];
                    GM_setValue("ELVENAR_TRACKED_ARMY", JSON.stringify(trackedArmy));
                }

                // I. Bắt kết quả trận đánh vừa diễn ra (InstantBattleResultVO & InstantSpireBattleResultVO)
                if ((node.__class__ === "InstantBattleResultVO" || node.__class__ === "InstantSpireBattleResultVO") && node.state) {
                    if (!trackedEncounter) trackedEncounter = { ts: now, src: "tournament", good: "", pSq: 0, eSq: 0, waves: [] };
                    let startTotal = 0;
                    let lostTotal = 0;
                    if (Array.isArray(node.state.unitsOrder)) {
                        node.state.unitsOrder.forEach(u => {
                            if (u && (u.teamFlag === 1 || u.playerId === 1)) {
                                const wt = (u.unitType && Number(u.unitType.unitWeight)) || 1;
                                const st = (Number(u.startAmountOfUnits !== undefined ? u.startAmountOfUnits : u.startUnitCount) || 0) * wt;
                                const cur = Math.max(0, Number(u.amountOfUnits !== undefined ? u.amountOfUnits : u.currentUnitCount) || 0) * wt;
                                startTotal += st;
                                lostTotal += Math.max(0, st - cur);
                                // Cập nhật chính xác % HP Buff thực tế từ startHitpoints / hitpoints
                                const sHp = Number(u.startHitpoints) || 0;
                                const bHp = (u.unitType && Number(u.unitType.hitpoints)) || 0;
                                if (sHp > 0 && bHp > 0 && trackedArmy) {
                                    const obsHpPct = Math.round(((sHp / bHp) - 1) * 1000) / 10;
                                    if (!Array.isArray(trackedArmy.buffs)) trackedArmy.buffs = [obsHpPct, 0, 0, 0, 0, 0];
                                    else trackedArmy.buffs[0] = obsHpPct;
                                }
                            }
                        });
                    }
                    const lossPct = startTotal > 0 ? Math.round((lostTotal / startTotal) * 1000) / 10 : 0;
                    trackedEncounter.lastResult = {
                        win: node.state.winnerBit === 1,
                        lossPct: lossPct,
                        wave: Number(node.completedWave) || 1,
                        totalWaves: Number(node.totalWaves) || 1,
                        ts: now
                    };
                    GM_setValue("ELVENAR_TRACKED_ENCOUNTER", JSON.stringify(trackedEncounter));
                    triggerLiveStreamPush();
                }

                if (Array.isArray(node)) {
                    for (let item of node) walk(item);
                } else {
                    for (let k in node) walk(node[k]);
                }
            }

            walk(data);
            saveStateCache();

            // BẮN TÍN HIỆU REALTIME SSE NGAY TỨC THÌ (<1s) KHI GAME CÓ BIẾN ĐỘNG
            triggerLiveStreamPush();
        } catch (e) {}
    }

    // --- 2.B BỘ ĐỆM GHI NHẬN GÓI TIN DEBUG (HỖ TRỢ XUẤT FILE DUMP PHÂN TÍCH CHUẨN XÁC 100% CẢ ĐÁNH TAY LẪN AUTO) ---
    const livePacketBuffer = [];
    win.__elvenar_live_dump = livePacketBuffer;

    function sanitizeRequestPayload(body) {
        if (!body || typeof body !== "string") return null;
        try {
            const parsedReq = JSON.parse(body);
            if (Array.isArray(parsedReq)) {
                return parsedReq.map(item => ({
                    requestClass: item.requestClass || item.service || "",
                    requestMethod: item.requestMethod || item.method || "",
                    requestData: item.requestData || item.params || null,
                    requestId: item.requestId || item.id || 0
                }));
            }
            if (parsedReq && typeof parsedReq === "object") {
                return {
                    requestClass: parsedReq.requestClass || parsedReq.service || "",
                    requestMethod: parsedReq.requestMethod || parsedReq.method || "",
                    requestData: parsedReq.requestData || parsedReq.params || null
                };
            }
        } catch (e) {}
        return null;
    }

    function checkCriticalBattlePacket(text, reqText = "", url = "") {
        const combined = text + " " + reqText + " " + url;
        return combined.includes("InstantBattleResultVO") ||
               combined.includes("InstantSpireBattleResultVO") ||
               combined.includes("BattleRealmStateVO") ||
               combined.includes("BattleStepVO") ||
               combined.includes("BattleUnitVO") ||
               combined.includes("BattleUnitTypeVO") ||
               combined.includes("AIPositionVO") ||
               combined.includes("AbilityVO") ||
               combined.includes("UnitBuffVO") ||
               combined.includes("BattlefieldService") ||
               combined.includes("BattleService") ||
               combined.includes("SpireBattleService") ||
               combined.includes("FightService") ||
               combined.includes("TournamentService") ||
               combined.includes("SpireService") ||
               combined.includes("EncounterVO") ||
               combined.includes("EncounterConfigVO") ||
               combined.includes("TournamentProvinceEncountersVO") ||
               combined.includes("SpireEncounter") ||
               combined.includes("enemyWaves") ||
               combined.includes("obstacle") ||
               combined.includes("Obstacle") ||
               combined.includes("terrain") ||
               combined.includes("Terrain") ||
               combined.includes("blockedField") ||
               combined.includes("BattleBoard") ||
               combined.includes("BattleGrid") ||
               combined.includes("StartupService");
    }

    function shouldProcessPacket(text, reqText = "") {
        const combined = text + " " + reqText;
        return combined.includes("CityProductionService") ||
               combined.includes("CityMapService") ||
               combined.includes("StartupService") ||
               combined.includes("CityResourcesService") ||
               combined.includes("CityResourceVO") ||
               combined.includes("ArmyService") ||
               combined.includes("ArmyDetails") ||
               combined.includes("BattlefieldService") ||
               combined.includes("WorldMapService") ||
               combined.includes("enemyWaves") ||
               combined.includes("Encounter") ||
               combined.includes("UnitSquad") ||
               combined.includes("unitSquad") ||
               combined.includes("unitTypeId") ||
               combined.includes("army_details") ||
               combined.includes("battleClusterSize") ||
               combined.includes("BattleService") ||
               combined.includes("SpireBattleService") ||
               combined.includes("FightService") ||
               combined.includes("TournamentService") ||
               combined.includes("Spire") ||
               combined.includes("Battle") ||
               combined.includes("obstacle") ||
               combined.includes("Obstacle") ||
               combined.includes("terrain") ||
               combined.includes("Terrain") ||
               combined.includes("blocked") ||
               combined.includes("barrack") ||
               combined.includes("workshop") ||
               combined.includes("ProductionQueue") ||
               combined.includes("AncientWonder") ||
               combined.includes("BuildingService") ||
               combined.includes("SpellService") ||
               combined.includes("Effect");
    }

    function recordPacketToBuffer(url, reqBodyStr, resText, parsedPayload) {
        try {
            const isCritical = checkCriticalBattlePacket(resText, reqBodyStr || "", url || "");
            const reqSummary = sanitizeRequestPayload(reqBodyStr);
            if (livePacketBuffer.length >= 8000) {
                const dropIdx = livePacketBuffer.findIndex(p => !p._critical);
                if (dropIdx !== -1) livePacketBuffer.splice(dropIdx, 1);
                else livePacketBuffer.shift();
            }
            const entry = {
                timestamp: new Date().toISOString(),
                url: url || "",
                _critical: isCritical,
                payload: parsedPayload
            };
            if (reqSummary) entry.request = reqSummary;
            livePacketBuffer.push(entry);
        } catch (e) {}
    }

    function downloadLiveDump() {
        if (!livePacketBuffer.length) {
            alert("⚠️ Chưa có dữ liệu gói tin nào được ghi nhận. Hãy thao tác trong game (thu hoạch lính, luyện lính, đánh trận...) rồi bấm lại!");
            return;
        }
        const jsonStr = JSON.stringify(livePacketBuffer, null, 2);
        const blob = new Blob([jsonStr], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        const timeStr = new Date().toISOString().replace(/[:.]/g, '-');
        a.download = `elvenar_debug_dump_live_${timeStr}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    if (typeof GM_registerMenuCommand !== 'undefined') {
        GM_registerMenuCommand("📥 Tải File Debug Dump JSON", downloadLiveDump);
    }

    const origOpen = win.XMLHttpRequest.prototype.open;
    const origSend = win.XMLHttpRequest.prototype.send;
    win.XMLHttpRequest.prototype.open = function(method, url, ...args) {
        this._url = url;
        return origOpen.apply(this, [method, url, ...args]);
    };
    win.XMLHttpRequest.prototype.send = function(body) {
        const reqBodyStr = (typeof body === "string") ? body : "";
        this.addEventListener('load', function() {
            try {
                const text = this.responseText;
                if (!text || (text[0] !== '{' && text[0] !== '[')) return;

                const parsed = JSON.parse(text);
                recordPacketToBuffer(this._url, reqBodyStr, text, parsed);

                if (!shouldProcessPacket(text, reqBodyStr)) return;
                handleData(parsed);
            } catch (e) {}
        });
        return origSend.apply(this, [body]);
    };

    // Hook thêm window.fetch để bắt trọn 100% nếu game tải bản đồ tĩnh (.json) hoặc gọi API qua Fetch
    if (typeof win.fetch === "function") {
        const origFetch = win.fetch;
        win.fetch = function(input, init) {
            const url = (typeof input === "string") ? input : (input && input.url ? input.url : "");
            const reqBodyStr = (init && typeof init.body === "string") ? init.body : "";
            return origFetch.apply(this, arguments).then(response => {
                try {
                    if (url && !url.includes("firebase") && !url.includes("workers.dev") && !url.includes("telegram.org")) {
                        const clone = response.clone();
                        clone.text().then(text => {
                            try {
                                if (!text || (text[0] !== '{' && text[0] !== '[')) return;
                                const parsed = JSON.parse(text);
                                recordPacketToBuffer(url, reqBodyStr, text, parsed);
                                if (shouldProcessPacket(text, reqBodyStr)) {
                                    handleData(parsed);
                                }
                            } catch (e) {}
                        }).catch(() => {});
                    }
                } catch (e) {}
                return response;
            });
        };
    }

    // --- 3. FORMAT THỜI GIAN HIỂN THỊ (HH:MM:SS HOẶC NGÀY GIỜ) ---
    function formatTime(seconds) {
        const s = Math.max(0, Math.floor(seconds));
        const d = Math.floor(s / 86400);
        const h = Math.floor((s % 86400) / 3600);
        const m = Math.floor((s % 3600) / 60);
        const remSec = s % 60;

        if (d > 0) {
            return `${d}d ${String(h).padStart(2, '0')}h ${String(m).padStart(2, '0')}m`;
        }
        return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(remSec).padStart(2, '0')}`;
    }

    // --- 4. TẠO NỘI DUNG DASHBOARD TELEGRAM ---
    function buildTelegramDashboardText() {
        const now = Math.floor(Date.now() / 1000);
        const timeString = new Date().toLocaleTimeString('vi-VN', { hour12: false });

        let msg = `🏰 <b>ELVENAR PRODUCTION DASHBOARD</b>\n`;
        msg += `⏱️ <i>Updated: ${timeString}</i>\n`;
        msg += `━━━━━━━━━━━━━━━━━━━━━\n\n`;

        // A. Military Queues
        msg += `⚔️ <b>MILITARY QUEUES</b>\n`;
        for (let key in militaryQueues) {
            const q = militaryQueues[key];
            const totalRemain = Math.max(0, q.totalFinishTime - now);
            const firstRemain = Math.max(0, q.firstSlotFinishTime - now);
            const slotCount = q.slots ? q.slots.length : 0;

            if (totalRemain > 0 && slotCount > 0) {
                msg += `🟢 <b>${q.name}</b> [${slotCount}/${q.maxSlots}]\n`;
                msg += `   ⌛ <code>${formatTime(totalRemain)}</code>  <i>(Batch 1: ${formatTime(firstRemain)})</i>\n`;
            } else {
                msg += `🔴 <b>${q.name}</b> [0/${q.maxSlots}] ➜ ⚠️ <i>Idle (Empty)</i>\n`;
            }
        }

        // B. Workshops
        msg += `\n🛠️ <b>MAIN WORKSHOPS</b>\n`;
        const wsList = Object.values(workshops);
        if (wsList.length === 0) {
            msg += `• <i>Waiting for workshop data...</i>\n`;
        } else {
            const maxLevel = Math.max(...wsList.map(w => w.level));
            const topWorkshops = wsList.filter(w => w.level === maxLevel);
            const totalCount = topWorkshops.length;

            let producingTimes = [];
            let readyCount = 0;
            let idleCount = 0;

            topWorkshops.forEach(ws => {
                const remain = Math.max(0, ws.finishTime - now);
                if (remain > 0) producingTimes.push(remain);
                else if (ws.status === "Ready" || (ws.finishTime > 0 && remain === 0)) readyCount++;
                else idleCount++;
            });

            if (producingTimes.length > 0) {
                // Đang sản xuất -> Reset mốc dừng
                if (wsStoppedSince !== 0) {
                    wsStoppedSince = 0;
                    GM_setValue("ELVENAR_WS_STOPPED_SINCE", 0);
                }

                const maxRemain = Math.max(...producingTimes);
                msg += `🟢 <b>${totalCount}x Workshops (Lv.${maxLevel})</b> [${producingTimes.length}/${totalCount}]\n`;
                msg += `   ⏳ <code>${formatTime(maxRemain)}</code>\n`;
                if (readyCount > 0) msg += `   ↳ 🟡 <i>${readyCount} ready to collect!</i>\n`;
                if (idleCount > 0) msg += `   ↳ 🔴 <i>${idleCount} idle!</i>\n`;
            } else {
                // Toàn bộ xưởng đã dừng sản xuất (Ready hoặc Idle)
                if (wsStoppedSince === 0) {
                    wsStoppedSince = now;
                    GM_setValue("ELVENAR_WS_STOPPED_SINCE", now);
                }
                const stoppedDuration = Math.max(0, now - wsStoppedSince);
                const stoppedStr = formatTime(stoppedDuration);

                if (readyCount > 0) {
                    msg += `🟡 <b>${totalCount}x Workshops (Lv.${maxLevel})</b> ➜ 📦 <b>Ready to collect!</b> [${readyCount}/${totalCount}]\n`;
                    msg += `   ↳ ⏸️ <i>Finished: <code>${stoppedStr}</code> ago</i>\n`;
                    if (idleCount > 0) msg += `   ↳ 🔴 <i>${idleCount} idle!</i>\n`;
                } else {
                    const alertTag = stoppedDuration >= 1800 ? ` ⚠️ <i>(Check Macro!)</i>` : ``;
                    msg += `🔴 <b>${totalCount}x Workshops (Lv.${maxLevel})</b> ➜ ⚠️ <i>Idle (All empty)</i>\n`;
                    msg += `   ↳ 🚨 <i>Stopped: <code>${stoppedStr}</code> ago</i>${alertTag}\n`;
                }
            }
        }

        // Bùa Power of Provision (Hiển thị ngay dưới Workshops)
        const spellRemain = Math.max(0, provisionSpellFinishTime - now);
        if (spellRemain > 0) {
            msg += `   ✨ <b>Power of Provision:</b> <code>${formatTime(spellRemain)}</code>\n`;
        } else {
            msg += `   ✨ <b>Power of Provision:</b> ⚠️ <i>Expired</i>\n`;
        }

        // C. Ancient Wonders
        msg += `\n🏛️ <b>ANCIENT WONDERS</b>\n`;
        for (let key in trackedAWs) {
            const aw = trackedAWs[key];
            const remain = Math.max(0, aw.finishTime - now);
            const lvTag = aw.level > 0 ? `(Lv.${aw.level})` : '';

            if (aw.status === "Producing" && remain > 0) {
                msg += `🟢 <b>${aw.name}</b> ${lvTag}\n`;
                msg += `   ⏳ <code>${formatTime(remain)}</code>\n`;
            } else if (aw.status === "Ready" || (aw.status === "Producing" && aw.finishTime > 0 && remain === 0)) {
                msg += `🟡 <b>${aw.name}</b> ${lvTag} ➜ 📦 <b>Ready to collect!</b>\n`;
            } else if (aw.status === "Upgrading") {
                msg += `🔨 <b>${aw.name}</b> ➜ <i>Upgrading (${formatTime(remain)})</i>\n`;
            } else {
                msg += `⚪ <b>${aw.name}</b> ${lvTag} ➜ <i>Idle</i>\n`;
            }
        }

        // D. Pet Food Buffs
        msg += `\n🐾 <b>PET FOOD BUFFS</b>\n`;
        for (let actId in trackedPets) {
            const pet = trackedPets[actId];
            const remain = Math.max(0, pet.finishTime - now);

            if (remain > 0) {
                msg += `🟢 <b>${pet.name}</b>\n`;
                msg += `   🍖 <code>${formatTime(remain)}</code>\n`;
            } else {
                msg += `🔴 <b>${pet.name}</b> ➜ ⚠️ <i>Hungry (Expired)</i>\n`;
            }
        }

        msg += `━━━━━━━━━━━━━━━━━━━━━`;
        // TÀNG HÌNH 100%: Dùng ký tự vô hình (Zero-Width Steganography)
        // Mắt người xem tin nhắn trên Telegram hoàn toàn KHÔNG THẤY GÌ (kể cả thanh spoiler hay chữ)
        // Nhưng WebApp vẫn bóc tách và đọc ngầm dữ liệu bình thường!
        try {
            const compact = buildCompactPayload(now);
            msg += encodeZeroWidthPayload(JSON.stringify(compact));
        } catch(e) {}
        return msg;
    }

    // --- 4.B MÃ HÓA TÀNG HÌNH BẰNG KÝ TỰ KHÔNG ĐỘ RỘNG (ZERO-WIDTH STEGANOGRAPHY) ---
    const ZW_CHARS = ['\u200B', '\u200C', '\u200D', '\u2060'];
    const ZW_START = '\uFEFF';

    function encodeZeroWidthPayload(str) {
        const binaryStr = unescape(encodeURIComponent(str));
        let out = ZW_START;
        for (let i = 0; i < binaryStr.length; i++) {
            const c = binaryStr.charCodeAt(i);
            out += ZW_CHARS[(c >> 6) & 3];
            out += ZW_CHARS[(c >> 4) & 3];
            out += ZW_CHARS[(c >> 2) & 3];
            out += ZW_CHARS[c & 3];
        }
        return out;
    }

    // --- 4.C XÂY DỰNG GÓI DỮ LIỆU ĐỒNG BỘ SIÊU GỌN (COMPACT PAYLOAD CHO TELEGRAM CLOUD) ---
    function buildCompactPayload(now) {
        // 1. Military: [Barracks, Training Grounds, Mercenary Camp]
        const m = [];
        for (let key in militaryQueues) {
            const q = militaryQueues[key];
            m.push([
                q.totalFinishTime || 0,
                q.firstSlotFinishTime || 0,
                q.slots ? q.slots.length : 0,
                q.maxSlots || 5
            ]);
        }

        // 2. Workshops: [c, l, f, p, r, pf, st, i]
        const wsList = Object.values(workshops);
        let w = [0, 0, 0, 0, 0, provisionSpellFinishTime || 0, wsStoppedSince || 0, 0];
        if (wsList.length > 0) {
            const maxLevel = Math.max(...wsList.map(item => item.level));
            const topWs = wsList.filter(item => item.level === maxLevel);
            let pTimes = [];
            let rCount = 0;
            let iCount = 0;
            let lastFinishTime = 0;
            topWs.forEach(item => {
                const rem = Math.max(0, item.finishTime - now);
                if (rem > 0) {
                    pTimes.push(item.finishTime);
                } else if (item.status === "Ready" || (item.finishTime > 0 && rem === 0)) {
                    rCount++;
                    if (item.finishTime > lastFinishTime) lastFinishTime = item.finishTime;
                } else {
                    iCount++;
                    if (item.finishTime > lastFinishTime) lastFinishTime = item.finishTime;
                }
            });

            // Đồng bộ mốc dừng wsStoppedSince & hẹn giờ bắn Realtime chính xác giây xưởng hoàn thành
            if (pTimes.length > 0) {
                scheduleWorkshopFinishCheck(Math.max(...pTimes), now);
                if (wsStoppedSince !== 0) {
                    wsStoppedSince = 0;
                    GM_setValue("ELVENAR_WS_STOPPED_SINCE", 0);
                }
            } else {
                if (wsStoppedSince === 0) {
                    wsStoppedSince = (lastFinishTime > 0 && lastFinishTime <= now) ? lastFinishTime : now;
                    GM_setValue("ELVENAR_WS_STOPPED_SINCE", wsStoppedSince);
                }
            }

            w = [
                topWs.length,
                maxLevel,
                pTimes.length > 0 ? Math.max(...pTimes) : 0,
                pTimes.length,
                rCount,
                provisionSpellFinishTime || 0,
                wsStoppedSince || 0,
                iCount
            ];
        }

        // 3. Ancient Wonders: [ [level, statusLetter, finishTime], ... ]
        const a = [];
        for (let key in trackedAWs) {
            const item = trackedAWs[key];
            const sChar = item.status === "Producing" ? "P" : (item.status === "Ready" ? "R" : (item.status === "Upgrading" ? "U" : "I"));
            a.push([
                item.level || 0,
                sChar,
                item.finishTime || 0
            ]);
        }

        // 4. Pets: [Brown Bear finishTime, Shellux finishTime]
        const p = [];
        for (let key in trackedPets) {
            p.push(trackedPets[key].finishTime || 0);
        }

        // 5. Standard Goods: [marble, steel, planks, crystal, scrolls, silk, elixir, magic_dust, gems]
        const r = buildCompactResourceData();

        // 6. Troop Reserves: [squadSize, [15 squad counts]]
        const arm = buildCompactArmyData();

        // 7. Active Battle Encounter: [ts, src, good, pSq, eSq, waves, lastResult]
        const enc = buildCompactEncounterData();

        return { t: now, m, w, a, p, r, arm, enc };
    }

    function buildCompactArmyData() {
        if (!trackedArmy || !trackedArmy.squads) return null;
        const keys = [
            "barracks_lm", "barracks_lr", "barracks_ma", "barracks_hm", "barracks_hr",
            "training_lm", "training_lr", "training_ma", "training_hm", "training_hr",
            "mercenary_lm", "mercenary_lr", "mercenary_ma", "mercenary_hm", "mercenary_hr"
        ];
        const tiers = trackedArmy.tiers || {};
        return [
            trackedArmy.squadSize || 0,
            keys.map(k => trackedArmy.squads[k] !== undefined ? trackedArmy.squads[k] : 0),
            keys.map(k => tiers[k] || 0),
            Array.isArray(trackedArmy.buffs) ? trackedArmy.buffs : null,
            Array.isArray(trackedArmy.spireBuffs) ? trackedArmy.spireBuffs : null
        ];
    }

    function buildCompactEncounterData() {
        if (!trackedEncounter || !Array.isArray(trackedEncounter.waves) || !trackedEncounter.waves.length) return null;
        const lr = trackedEncounter.lastResult;
        const obs = Array.isArray(trackedEncounter.obstacles) ? trackedEncounter.obstacles : null;
        return [
            trackedEncounter.ts || 0,
            trackedEncounter.src || "tournament",
            trackedEncounter.good || "",
            trackedEncounter.pSq || 0,
            trackedEncounter.eSq || 0,
            trackedEncounter.waves,
            lr ? [lr.win ? 1 : 0, lr.lossPct || 0, lr.wave || 1, lr.totalWaves || 1] : null,
            obs,
            trackedEncounter.provKey || ""
        ];
    }

    // --- 4.C ĐƯỜNG DẪN TELEGRAM NATIVE MINI APP ---
    function buildMiniAppUrl() {
        return MINI_APP_GROUP_URL;
    }

    // --- 4.D EVENT-DRIVEN REALTIME TRIGGER KHI GAME CÓ BIẾN ĐỘNG ---
    let wsFinishTimer = null;
    function scheduleWorkshopFinishCheck(finishTime, now) {
        if (wsFinishTimer) clearTimeout(wsFinishTimer);
        const diffMs = (finishTime - now) * 1000 + 1000; // Thêm 1s để chắc chắn qua mốc 0s
        if (diffMs > 0 && diffMs <= 86400000) { // Trong vòng 24h
            wsFinishTimer = setTimeout(() => {
                console.log("[Live Radar] Xưởng vừa hoàn thành sản xuất, tự động bắn cập nhật Realtime!");
                syncLiveTelegramDashboard(true);
            }, diffMs);
        }
    }

    function triggerLiveStreamPush() {
        if (liveStreamDebounce) clearTimeout(liveStreamDebounce);
        liveStreamDebounce = setTimeout(() => {
            syncLiveTelegramDashboard();
        }, 300); // 300ms gom chuột siêu tốc (gom mượt thao tác kéo chuột và bắn tức thì trong 0.3s)
    }

    let privateChatBlockedUntil = 0;
    let lastGroupPinCheckTime = 0;

    function createOrUpdateGameBadge() {
        if (typeof document === 'undefined' || !document.body) return null;
        let badge = document.getElementById("elvenarLiveRadarBadge");
        if (!badge) {
            badge = document.createElement("div");
            badge.id = "elvenarLiveRadarBadge";
            badge.style.cssText = `
                position: fixed;
                top: 6px;
                left: 6px;
                z-index: 9999999;
                background: rgba(15, 23, 42, 0.88);
                color: #38bdf8;
                border: 1px solid rgba(56, 189, 248, 0.4);
                border-radius: 9999px;
                padding: 4px 10px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                font-size: 11px;
                font-weight: 700;
                cursor: pointer;
                box-shadow: 0 4px 16px rgba(0,0,0,0.6);
                display: flex;
                align-items: center;
                gap: 5px;
                backdrop-filter: blur(8px);
                user-select: none;
                transition: all 0.2s ease;
            `;
            badge.innerText = "Radar: Waiting...";
            badge.title = "Chuột trái: Đồng bộ tức thì | Chuột phải: Tải file Debug Dump JSON";
            badge.onclick = function() {
                badge.innerText = "Syncing...";
                syncLiveTelegramDashboard(true);
            };
            badge.oncontextmenu = function(e) {
                e.preventDefault();
                downloadLiveDump();
            };
            document.body.appendChild(badge);
        }
        return badge;
    }

    function updateGameBadge(ok, text) {
        const badge = createOrUpdateGameBadge();
        if (!badge) return;
        badge.innerText = text;
        badge.style.borderColor = ok ? "rgba(52, 211, 153, 0.5)" : "rgba(244, 63, 94, 0.6)";
        badge.style.color = ok ? "#34d399" : "#f43f5e";
    }

    // --- 5. ĐỒNG BỘ REALTIME SIÊU TỐC QUA CLOUDFLARE & TELEGRAM ---
    function syncLiveTelegramDashboard(force = false) {
        try {
            const now = Math.floor(Date.now() / 1000);
            const compactPayload = buildCompactPayload(now);

            // 🎯 LỌC BIẾN ĐỘNG THÔNG MINH: Chỉ gửi khi dữ liệu game thực sự thay đổi, hoặc sau 5 phút heartbeat, hoặc bấm thủ công
            const currentSignature = JSON.stringify({
                m: compactPayload.m,
                w: compactPayload.w,
                a: compactPayload.a,
                p: compactPayload.p,
                r: compactPayload.r,
                arm: compactPayload.arm,
                enc: compactPayload.enc
            });
            const hasDataChanged = (currentSignature !== lastSentDataSignature);

            if (!hasDataChanged && !force && (Date.now() - lastSuccessfulSyncTime < 300000)) {
                // Không có biến động về lính, xưởng, kỳ quan, pet hay tài nguyên -> KHÔNG GỬI GÌ CẢ
                return;
            }

            // 1. GỬI LÊN GOOGLE FIREBASE REALTIME (ƯU TIÊN TUYỆT ĐỐI - TỐC ĐỘ <50ms WEBSOCKET PUSH)
            if (FIREBASE_DATABASE_URL) {
                GM_xmlhttpRequest({
                    method: "PUT",
                    url: FIREBASE_DATABASE_URL,
                    headers: { "Content-Type": "application/json" },
                    data: JSON.stringify(compactPayload),
                    onload: function(res) {
                        try {
                            const json = JSON.parse(res.responseText);
                            if (json && json.t) {
                                lastSentDataSignature = currentSignature;
                                lastSuccessfulSyncTime = Date.now();
                                const timeStr = new Date().toLocaleTimeString('vi-VN', { hour12: false });
                                updateGameBadge(true, `Radar: Live (${timeStr})`);
                            }
                        } catch(e) {}
                    },
                    onerror: function(err) {
                        console.warn("[Firebase] Lỗi gửi dữ liệu:", err);
                    }
                });
            }

            // 2. GỬI BACKUP LÊN CLOUDFLARE WORKER (Dự phòng nền)
            if (CLOUDFLARE_WORKER_URL) {
                GM_xmlhttpRequest({
                    method: "POST",
                    url: CLOUDFLARE_WORKER_URL,
                    headers: { "Content-Type": "application/json" },
                    data: JSON.stringify(compactPayload)
                });
            }

            // 2. ĐỒNG BỘ TELEGRAM (Chạy ngầm phụ, có cơ chế Rate-limiting bảo vệ bot)
            if (!TELEGRAM_BOT_TOKEN || TELEGRAM_BOT_TOKEN === "DIEN_TOKEN_BOT_CUA_BAN") return;

            // Cơ chế khóa chống gửi chồng chéo Telegram
            if (isUpdating) {
                if (Date.now() - isUpdatingTime > 12000) {
                    isUpdating = false;
                } else {
                    return;
                }
            }

            // Chống gửi quá dày đặc Telegram (tối đa 1 lần mỗi 2.5 giây)
            const timeSinceLastCall = Date.now() - lastTelegramApiCallTime;
            if (timeSinceLastCall < 2500 && !force) {
                return;
            }

            const currentText = buildTelegramDashboardText();
            isUpdating = true;
            isUpdatingTime = Date.now();
            lastTelegramApiCallTime = Date.now();

            // Cập nhật vào Chat riêng (Nếu không bị Telegram 429 flood wait)
            if (TELEGRAM_PRIVATE_CHAT_ID && Date.now() > privateChatBlockedUntil) {
                const privateReplyMarkup = {
                    inline_keyboard: [[
                        { text: "📱 Mở Mini App Realtime", web_app: { url: MINI_APP_WEB_URL } }
                    ]]
                };
                syncToTargetChat(TELEGRAM_PRIVATE_CHAT_ID, null, livePrivateMsgId, currentText, privateReplyMarkup, true);
            }

            // Cập nhật vào Topic 26 Nhóm chung (HOÀN TOÀN KHÔNG GHIM)
            if (TELEGRAM_CHAT_ID) {
                const groupReplyMarkup = {
                    inline_keyboard: [[
                        { text: "📱 Mở Dashboard Realtime", url: MINI_APP_WEB_URL }
                    ]]
                };
                syncToTargetChat(TELEGRAM_CHAT_ID, TELEGRAM_TOPIC_ID, liveGroupMsgId, currentText, groupReplyMarkup, false);
            }
        } catch (err) {
            console.error("[Live Radar] Lỗi trong syncLiveTelegramDashboard:", err);
            updateGameBadge(false, "Radar: Error");
            isUpdating = false;
        }
    }

    function syncToTargetChat(chatId, topicId, msgId, text, replyMarkup, shouldPin) {
        if (msgId) {
            GM_xmlhttpRequest({
                method: "POST",
                url: `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/editMessageText`,
                headers: { "Content-Type": "application/json" },
                data: JSON.stringify({
                    chat_id: chatId,
                    message_id: msgId,
                    text: text,
                    parse_mode: "HTML",
                    reply_markup: replyMarkup
                }),
                onload: function(res) {
                    try {
                        const json = JSON.parse(res.responseText);
                        const timeStr = new Date().toLocaleTimeString('vi-VN', { hour12: false });
                        if (json.ok) {
                            lastSentText = text;
                            updateGameBadge(true, `Radar: Sent (${timeStr})`);
                            if (shouldPin) {
                                console.log("[Telegram Live] Đồng bộ Chat riêng thành công lúc " + timeStr);
                                if (Date.now() - lastPinCheckTime > 120000) {
                                    lastPinCheckTime = Date.now();
                                    tryPinMessage(chatId, msgId);
                                }
                            } else {
                                console.log("[Telegram Live] Đồng bộ Topic 26 thành công lúc " + timeStr);
                            }
                        } else {
                            if (json.description && json.description.includes("message is not modified")) {
                                updateGameBadge(true, `Radar: Synced (${timeStr})`);
                                return;
                            }
                            if (json.error_code === 429) {
                                const retryAfter = (json.parameters && json.parameters.retry_after) || 60;
                                console.warn(`[Telegram Live] Chat ${chatId} bị 429 Flood Wait, tạm dừng gửi chat này ${retryAfter}s`);
                                if (chatId === TELEGRAM_PRIVATE_CHAT_ID) {
                                    privateChatBlockedUntil = Date.now() + (retryAfter + 5) * 1000;
                                }
                            } else if (json.description && (json.description.includes("message to edit not found") || json.description.includes("message can't be edited"))) {
                                createTargetMessage(chatId, topicId, text, replyMarkup, shouldPin);
                            } else {
                                console.warn(`[Telegram Live] Chat ${chatId} lỗi:`, json.description);
                            }
                        }
                    } catch(e) {}
                    finally {
                        isUpdating = false;
                    }
                },
                onerror: function(err) {
                    console.warn(`[Telegram Live] Kết nối mạng lỗi tới chat ${chatId}:`, err);
                    isUpdating = false;
                }
            });
        } else {
            createTargetMessage(chatId, topicId, text, replyMarkup, shouldPin);
        }
    }

    function createTargetMessage(chatId, topicId, text, replyMarkup, shouldPin) {
        const payload = {
            chat_id: chatId,
            text: text,
            parse_mode: "HTML",
            reply_markup: replyMarkup
        };
        if (topicId !== null && topicId !== undefined && topicId !== "") {
            payload.message_thread_id = Number(topicId);
        }

        GM_xmlhttpRequest({
            method: "POST",
            url: `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`,
            headers: { "Content-Type": "application/json" },
            data: JSON.stringify(payload),
            onload: function(res) {
                try {
                    const json = JSON.parse(res.responseText);
                    if (json.ok && json.result && json.result.message_id) {
                        const newMsgId = json.result.message_id;
                        const timeStr = new Date().toLocaleTimeString('vi-VN', { hour12: false });
                        updateGameBadge(true, `Radar: Created (${timeStr})`);
                        if (shouldPin) {
                            livePrivateMsgId = newMsgId;
                            GM_setValue("ELVENAR_LIVE_PRIVATE_MSG_ID", newMsgId);
                            tryPinMessage(chatId, newMsgId);
                        } else {
                            liveGroupMsgId = newMsgId;
                            GM_setValue("ELVENAR_LIVE_GROUP_MSG_ID", newMsgId);
                            tryPinMessage(chatId, newMsgId);
                        }
                    }
                } catch(e) {}
                finally {
                    isUpdating = false;
                }
            },
            onerror: function() {
                isUpdating = false;
            }
        });
    }

    function tryPinMessage(chatId, msgId) {
        GM_xmlhttpRequest({
            method: "POST",
            url: `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/pinChatMessage`,
            headers: { "Content-Type": "application/json" },
            data: JSON.stringify({
                chat_id: chatId,
                message_id: msgId,
                disable_notification: true
            })
        });
    }

    // --- 7. KHỞI CHẠY TIẾN TRÌNH NGẦM ---
    setTimeout(createOrUpdateGameBadge, 1500);
    setTimeout(createOrUpdateGameBadge, 4000);
    setTimeout(syncLiveTelegramDashboard, 2500);
    setTimeout(initCloudMapsSync, 2000);
    setTimeout(initCloudLedgerSync, 3500);
    setInterval(syncLiveTelegramDashboard, TELEGRAM_SYNC_INTERVAL_SEC * 1000);

})();
