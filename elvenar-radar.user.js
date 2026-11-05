// ==UserScript==
// @name         Elvenar Radar
// @namespace    http://tampermonkey.net/
// @version      6.2.9
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
        squadSize: 4299,
        squads: {
            "barracks_lm": 20.8, "barracks_lr": 513, "barracks_ma": 258, "barracks_hm": 233, "barracks_hr": 400,
            "training_lm": 217, "training_lr": 157, "training_ma": 195, "training_hm": 15.6, "training_hr": 131,
            "mercenary_lm": 196, "mercenary_lr": 174, "mercenary_ma": 207, "mercenary_hm": 216, "mercenary_hr": 245
        },
        raw: {}
    };

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
        "eb_lm": 1, "eb_lr": 1, "eb_ma": 4, "eb_hm": 6, "eb_hr": 6,
        "hb_lm": 1, "hb_lr": 1, "hb_ma": 4, "hb_hm": 6, "hb_hr": 6,
        "tg_lm": 1, "tg_lr": 2, "tg_ma": 3, "tg_hm": 2, "tg_hr": 2,
        "mc_lm": 1, "mc_lr": 2, "mc_ma": 2, "mc_hm": 3, "mc_hr": 3
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

    function updateSingleSquad(sq, clusterSize) {
        if (!sq || !sq.unitTypeId) return false;
        const prefix = sq.unitTypeId.substring(0, 5);
        const cellKey = troopKeyMap[prefix];
        if (!cellKey) return false;
        const weight = troopWeightMap[prefix] || 1;
        const size = sq.size !== undefined ? sq.size : (sq.amount !== undefined ? sq.amount : (sq.count !== undefined ? sq.count : 0));
        const effectiveCluster = clusterSize || (trackedArmy && trackedArmy.squadSize) || 4299;
        if (!trackedArmy) trackedArmy = { squadSize: effectiveCluster, squads: {}, raw: {} };
        if (!trackedArmy.raw) trackedArmy.raw = {};
        if (!trackedArmy.squads) trackedArmy.squads = {};
        trackedArmy.squadSize = effectiveCluster;
        trackedArmy.raw[cellKey] = size;
        const numSquads = (size * weight) / effectiveCluster;
        trackedArmy.squads[cellKey] = Math.round(numSquads * 10) / 10;
        return true;
    }

    // --- 2. BẮT GÓI TIN GAME ---
    function handleData(data) {
        try {
            const now = Math.floor(Date.now() / 1000);

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
                        const level = match ? parseInt(match[0], 10) : (workshops[uid]?.level || 15);

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

                // D. Bắt dữ liệu kho Hàng Hóa Tiêu Chuẩn (CHỈ nhận kho thực của người chơi, bỏ qua chi phí nâng cấp nhà)
                if (node.__class__ === "CityResourceVO" && node.resources && Object.keys(node.resources).length >= 10 && node.resources.money !== undefined && node.resources.marble !== undefined) {
                    processCityResources(node.resources);
                }

                // E. Bắt dữ liệu Quân Đội & Quân Số Dự Bị (ArmyDetailsVO, unitSquads, UnitSquadVO)
                if (node.__class__ === "ArmyDetailsVO" || (node.battleClusterSize && Array.isArray(node.unitSquads)) || (node.army_details && Array.isArray(node.army_details.unitSquads))) {
                    const armyObj = node.army_details || node;
                    const clusterSize = armyObj.battleClusterSize || (trackedArmy && trackedArmy.squadSize) || 4299;
                    if (!trackedArmy) trackedArmy = { squadSize: clusterSize, squads: {}, raw: {} };
                    trackedArmy.squadSize = clusterSize;
                    let changed = false;
                    if (Array.isArray(armyObj.unitSquads)) {
                        armyObj.unitSquads.forEach(sq => {
                            if (updateSingleSquad(sq, clusterSize)) changed = true;
                        });
                    }
                    if (changed) {
                        GM_setValue("ELVENAR_TRACKED_ARMY", JSON.stringify(trackedArmy));
                        triggerLiveStreamPush();
                    }
                } else if (Array.isArray(node.unitSquads)) {
                    const clusterSize = (trackedArmy && trackedArmy.squadSize) || 4299;
                    let changed = false;
                    node.unitSquads.forEach(sq => {
                        if (updateSingleSquad(sq, clusterSize)) changed = true;
                    });
                    if (changed) {
                        GM_setValue("ELVENAR_TRACKED_ARMY", JSON.stringify(trackedArmy));
                        triggerLiveStreamPush();
                    }
                } else if (node.__class__ === "UnitSquadVO" || (node.unitTypeId && (node.size !== undefined || node.amount !== undefined || node.count !== undefined))) {
                    const clusterSize = (trackedArmy && trackedArmy.squadSize) || 4299;
                    if (updateSingleSquad(node, clusterSize)) {
                        GM_setValue("ELVENAR_TRACKED_ARMY", JSON.stringify(trackedArmy));
                        triggerLiveStreamPush();
                    }
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

    const origOpen = win.XMLHttpRequest.prototype.open;
    const origSend = win.XMLHttpRequest.prototype.send;
    win.XMLHttpRequest.prototype.open = function(method, url, ...args) {
        this._url = url;
        return origOpen.apply(this, [method, url, ...args]);
    };
    win.XMLHttpRequest.prototype.send = function(body) {
        this.addEventListener('load', function() {
            try {
                const text = this.responseText;
                if (!text || (text[0] !== '{' && text[0] !== '[')) return;
                if (!text.includes("CityProductionService") &&
                    !text.includes("CityMapService") &&
                    !text.includes("StartupService") &&
                    !text.includes("CityResourcesService") &&
                    !text.includes("CityResourceVO") &&
                    !text.includes("ArmyDetails") &&
                    !text.includes("UnitSquad") &&
                    !text.includes("unitSquad") &&
                    !text.includes("unitTypeId") &&
                    !text.includes("army_details") &&
                    !text.includes("battleClusterSize") &&
                    !text.includes("BattleService") &&
                    !text.includes("FightService") &&
                    !text.includes("TournamentService") &&
                    !text.includes("SpireService") &&
                    !text.includes("barrack") &&
                    !text.includes("workshop") &&
                    !text.includes("ProductionQueue") &&
                    !text.includes("AncientWonder") &&
                    !text.includes("BuildingService") &&
                    !text.includes("SpellService") &&
                    !text.includes("Effect")) return;

                const data = JSON.parse(text);
                handleData(data);
            } catch (e) {}
        });
        return origSend.apply(this, [body]);
    };

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
        let w = [0, 15, 0, 0, 0, provisionSpellFinishTime || 0, wsStoppedSince || 0, 0];
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

        return { t: now, m, w, a, p, r, arm };
    }

    function buildCompactArmyData() {
        if (!trackedArmy || !trackedArmy.squads) return null;
        const keys = [
            "barracks_lm", "barracks_lr", "barracks_ma", "barracks_hm", "barracks_hr",
            "training_lm", "training_lr", "training_ma", "training_hm", "training_hr",
            "mercenary_lm", "mercenary_lr", "mercenary_ma", "mercenary_hm", "mercenary_hr"
        ];
        return [
            trackedArmy.squadSize || 4299,
            keys.map(k => trackedArmy.squads[k] !== undefined ? trackedArmy.squads[k] : 0)
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
            badge.title = "Click to force sync live data";
            badge.onclick = function() {
                badge.innerText = "Syncing...";
                syncLiveTelegramDashboard(true);
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
                arm: compactPayload.arm
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
    setTimeout(initCloudLedgerSync, 3500);
    setInterval(syncLiveTelegramDashboard, TELEGRAM_SYNC_INTERVAL_SEC * 1000);

})();
