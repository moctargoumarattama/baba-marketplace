/**
 * Micro-service WhatsApp Baba Market (/home/moctar/baba-whatsapp/server.js)
 * Basé sur @whiskeysockets/baileys — écoute sur 127.0.0.1:3002
 *
 * Endpoints existants conservés :
 *   - GET  /api/status (/status, /health)
 *   - POST /api/send
 *   - POST /api/logout (/logout, /api/disconnect, /disconnect)
 *   - POST /api/reconnect (/reconnect, /api/qr/refresh)
 *
 * Nouveaux endpoints pour l'automatisation promotionnelle :
 *   - POST /api/promo/status      -> publie un Statut 24h (status@broadcast) avec photo + légende
 *   - POST /api/promo/send-media  -> envoie une photo + légende à un numéro opt-in (avec vérification STOP + onWhatsApp)
 */

const express = require("express");
const fs = require("fs");
const path = require("path");
const pino = require("pino");
const QRCode = require("qrcode");
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require("@whiskeysockets/baileys");

const PORT = parseInt(process.env.PORT || "3002", 10);
const HOST = process.env.HOST || "127.0.0.1";
const API_KEY = (process.env.BABA_WHATSAPP_API_KEY || "").trim();
const AUTH_DIR = path.join(__dirname, "auth_info_baileys");
const OPT_OUT_FILE = path.join(__dirname, "opt_outs.json");
const MAX_IMAGE_BYTES = 8 * 1024 * 1024; // 8 Mo

const ALLOWED_IMAGE_HOSTS = new Set(
  (process.env.ALLOWED_IMAGE_HOSTS || "www.babamarket.ma,babamarket.ma,127.0.0.1,localhost")
    .split(",")
    .map((h) => h.trim().toLowerCase())
    .filter(Boolean)
);

const logger = pino({ level: process.env.LOG_LEVEL || "warn" });

// Protection contre les plantages silencieux du processus Node.js
process.on("uncaughtException", (err) => {
  logger.error({ err: err?.message || err, stack: err?.stack }, "Erreur non capturée dans le micro-service WhatsApp");
});
process.on("unhandledRejection", (reason) => {
  logger.error({ reason: reason?.message || reason }, "Rejet de promesse non capturé dans le micro-service WhatsApp");
});

const app = express();
app.use(express.json({ limit: "15mb" }));
app.use(express.urlencoded({ extended: true, limit: "15mb" }));

let sock = null;
let connectionStatus = "disconnected"; // connected | qr_ready | disconnected
let latestQrDataUri = null;
let connectedPhone = null;
let isConnecting = false;

// ---------------------------------------------------------------------------
// Gestion de la liste STOP (opt-out persistant sur disque)
// ---------------------------------------------------------------------------
function loadOptOuts() {
  try {
    if (!fs.existsSync(OPT_OUT_FILE)) return new Set();
    const raw = JSON.parse(fs.readFileSync(OPT_OUT_FILE, "utf8"));
    return new Set(Array.isArray(raw) ? raw.map(String) : []);
  } catch (_err) {
    return new Set();
  }
}

function saveOptOuts(set) {
  try {
    fs.writeFileSync(OPT_OUT_FILE, JSON.stringify([...set], null, 2), "utf8");
  } catch (err) {
    logger.error({ err }, "Impossible d'enregistrer opt_outs.json");
  }
}

const optedOutPhones = loadOptOuts();

// ---------------------------------------------------------------------------
// Gestion des contacts connus pour la diffusion des Statuts 24h
// WhatsApp/Baileys exige une liste explicite (statusJidList) pour distribuer les statuts
// ---------------------------------------------------------------------------
const CONTACTS_FILE = path.join(__dirname, "known_contacts.json");

function loadKnownContacts() {
  try {
    if (!fs.existsSync(CONTACTS_FILE)) return new Set();
    const raw = JSON.parse(fs.readFileSync(CONTACTS_FILE, "utf8"));
    return new Set(Array.isArray(raw) ? raw.map(String).filter((s) => s.endsWith("@s.whatsapp.net")) : []);
  } catch (_err) {
    return new Set();
  }
}

function saveKnownContacts(set) {
  try {
    fs.writeFileSync(CONTACTS_FILE, JSON.stringify([...set], null, 2), "utf8");
  } catch (err) {
    logger.error({ err }, "Impossible d'enregistrer known_contacts.json");
  }
}

const knownContacts = loadKnownContacts();

function rememberJids(jids) {
  let changed = false;
  for (const raw of jids || []) {
    const jid = String(raw || "").trim();
    if (jid && jid.endsWith("@s.whatsapp.net") && !jid.includes("@broadcast") && !knownContacts.has(jid)) {
      knownContacts.add(jid);
      changed = true;
    }
  }
  if (changed) {
    saveKnownContacts(knownContacts);
  }
}

function normalizePhone(raw) {
  let digits = String(raw || "").replace(/\D/g, "");
  if (!digits) return "";
  if (digits.startsWith("00")) digits = digits.slice(2);
  if (digits.length === 10 && digits.startsWith("0") && (digits[1] === "6" || digits[1] === "7")) {
    return "212" + digits.slice(1);
  }
  if (digits.length === 9 && (digits[0] === "6" || digits[0] === "7")) {
    return "212" + digits;
  }
  return digits;
}

function toJid(phone) {
  const digits = normalizePhone(phone);
  return digits ? `${digits}@s.whatsapp.net` : "";
}

function extractInviteCode(urlOrText) {
  if (!urlOrText) return null;
  const match = String(urlOrText).match(/(?:chat\.whatsapp\.com\/|invite\/)([A-Za-z0-9_-]+)/i);
  return match ? match[1] : null;
}

async function resolveTargetJid(rawTarget) {
  const str = String(rawTarget || "").trim();
  if (!str) return null;

  // 1. Déjà un JID de groupe WhatsApp (ex: 120363024888888888@g.us)
  if (str.endsWith("@g.us")) {
    return { jid: str, isGroup: true, label: str };
  }
  // Format JID numérique sans le suffixe @g.us
  if (/^120363\d+$/.test(str)) {
    return { jid: `${str}@g.us`, isGroup: true, label: `${str}@g.us` };
  }

  // 2. Lien d'invitation de groupe (ex: https://chat.whatsapp.com/AbCdEf...)
  const inviteCode = extractInviteCode(str);
  if (inviteCode && sock) {
    let groupJid = null;
    let groupSubject = str;

    // A. Tenter de rejoindre le groupe s'il n'est pas déjà rejoint
    try {
      const joinedId = await sock.groupAcceptInvite(inviteCode);
      if (joinedId) {
        groupJid = joinedId.endsWith("@g.us") ? joinedId : `${joinedId}@g.us`;
      }
    } catch (joinErr) {
      logger.debug({ inviteCode, err: joinErr && joinErr.message }, "groupAcceptInvite (peut-être déjà membre)");
    }

    // B. Obtenir les informations du groupe (JID et Sujet)
    try {
      const info = await sock.groupGetInviteInfo(inviteCode);
      if (info && info.id) {
        if (!groupJid) {
          groupJid = info.id.endsWith("@g.us") ? info.id : `${info.id}@g.us`;
        }
        groupSubject = info.subject || groupSubject;
      }
    } catch (infoErr) {
      logger.warn({ inviteCode, err: infoErr && infoErr.message }, "groupGetInviteInfo");
    }

    if (groupJid) {
      return { jid: groupJid, isGroup: true, label: groupSubject };
    }
  }

  // 3. Recherche intelligente par NOM DU GROUPE parmi les groupes du compte connecté !
  // Très utile quand l'admin tape le nom du groupe qu'il a lui-même créé sur son téléphone
  if (sock && typeof sock.groupFetchAllParticipating === "function") {
    try {
      const participating = await sock.groupFetchAllParticipating();
      const lower = str.toLowerCase();
      for (const [gid, meta] of Object.entries(participating || {})) {
        const subj = String(meta?.subject || "").trim().toLowerCase();
        if (subj && (subj === lower || subj.includes(lower) || lower.includes(subj))) {
          logger.info({ matchedGroup: meta.subject, gid }, "Groupe résolu par son nom");
          return { jid: gid, isGroup: true, label: meta.subject || gid };
        }
      }
    } catch (fetchErr) {
      logger.debug({ err: fetchErr?.message }, "Erreur groupFetchAllParticipating dans resolveTargetJid");
    }
  }

  // 4. Numéro de téléphone individuel (contact opt-in)
  const digits = normalizePhone(str);
  if (digits) {
    return { jid: `${digits}@s.whatsapp.net`, isGroup: false, phone: digits, label: digits };
  }

  return null;
}

function isStopKeyword(text) {
  const cleaned = String(text || "")
    .trim()
    .toLowerCase()
    .replace(/[!.,?]/g, "");
  return ["stop", "arret", "arrêt", "desinscrire", "désinscrire", "unsubscribe"].includes(cleaned);
}

// ---------------------------------------------------------------------------
// Téléchargement sécurisé de la photo produit (protection SSRF)
// ---------------------------------------------------------------------------
async function fetchImageBuffer(imageUrl) {
  let parsed;
  try {
    parsed = new URL(String(imageUrl || ""));
  } catch (_err) {
    throw new Error("invalid_image_url");
  }
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("invalid_image_protocol");
  }
  if (!ALLOWED_IMAGE_HOSTS.has(parsed.hostname.toLowerCase())) {
    throw new Error("disallowed_image_host");
  }

  // En production, si l'URL publique pointe sur babamarket.ma, on peut lire directement via 127.0.0.1:5002
  const localRewrite = process.env.LOCAL_BACKEND_ORIGIN || "http://127.0.0.1:5002";
  const targetUrl =
    parsed.hostname.endsWith("babamarket.ma") && localRewrite
      ? `${localRewrite.replace(/\/$/, "")}${parsed.pathname}${parsed.search}`
      : parsed.toString();

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const resp = await fetch(targetUrl, {
      signal: controller.signal,
      headers: { "User-Agent": "BabaMarket-WhatsApp-Gateway/1.0" },
    });
    if (!resp.ok) {
      throw new Error(`image_http_${resp.status}`);
    }
    const arrayBuffer = await resp.arrayBuffer();
    if (arrayBuffer.byteLength === 0 || arrayBuffer.byteLength > MAX_IMAGE_BYTES) {
      throw new Error("image_size_invalid");
    }
    return Buffer.from(arrayBuffer);
  } finally {
    clearTimeout(timer);
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Connexion Baileys
// ---------------------------------------------------------------------------
async function startSocket() {
  if (isConnecting) return;
  isConnecting = true;
  try {
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const { version } = await fetchLatestBaileysVersion();

    sock = makeWASocket({
      version,
      logger,
      auth: state,
      printQRInTerminal: false,
      markOnlineOnConnect: false,
      syncFullHistory: false,
    });

    sock.ev.on("creds.update", saveCreds);

    // Synchronisation automatique des contacts pour la diffusion des Statuts 24h
    sock.ev.on("contacts.upsert", (contacts) => {
      try {
        rememberJids((contacts || []).map((c) => c?.id));
      } catch (err) {
        logger.warn({ err: err?.message }, "contacts.upsert error");
      }
    });
    sock.ev.on("contacts.update", (contacts) => {
      try {
        rememberJids((contacts || []).map((c) => c?.id));
      } catch (err) {
        logger.warn({ err: err?.message }, "contacts.update error");
      }
    });
    sock.ev.on("messaging-history.set", (payload) => {
      try {
        const contacts = payload && Array.isArray(payload.contacts) ? payload.contacts : [];
        const chats = payload && Array.isArray(payload.chats) ? payload.chats : [];
        rememberJids(contacts.map((c) => c?.id));
        rememberJids(chats.map((ch) => ch?.id));
      } catch (err) {
        logger.warn({ err: err?.message }, "messaging-history.set error");
      }
    });
    sock.ev.on("chats.upsert", (chats) => {
      try {
        rememberJids((chats || []).map((ch) => ch?.id));
      } catch (err) {
        logger.warn({ err: err?.message }, "chats.upsert error");
      }
    });

    sock.ev.on("connection.update", async (update) => {
      const { connection, lastDisconnect, qr } = update;
      if (qr) {
        try {
          latestQrDataUri = await QRCode.toDataURL(qr, { margin: 1, width: 280 });
          connectionStatus = "qr_ready";
        } catch (_err) {
          latestQrDataUri = null;
        }
      }
      if (connection === "open") {
        connectionStatus = "connected";
        latestQrDataUri = null;
        const rawId = (sock.user && sock.user.id) || "";
        connectedPhone = rawId.split(":")[0].split("@")[0].replace(/\D/g, "") || null;
      } else if (connection === "close") {
        const statusCode =
          lastDisconnect &&
          lastDisconnect.error &&
          lastDisconnect.error.output &&
          lastDisconnect.error.output.statusCode;
        const loggedOut = statusCode === DisconnectReason.loggedOut;
        connectionStatus = "disconnected";
        connectedPhone = null;
        if (!loggedOut) {
          setTimeout(() => startSocket(), 4000);
        }
      }
    });

    // Écoute automatique du mot-clé STOP pour désinscrire immédiatement le contact
    sock.ev.on("messages.upsert", async ({ messages, type }) => {
      if (type !== "notify" || !Array.isArray(messages)) return;
      for (const msg of messages) {
        if (!msg || !msg.message || msg.key.fromMe) continue;
        const remoteJid = String(msg.key.remoteJid || "");
        if (!remoteJid.endsWith("@s.whatsapp.net")) continue;
        rememberJids([remoteJid]);
        const text =
          msg.message.conversation ||
          (msg.message.extendedTextMessage && msg.message.extendedTextMessage.text) ||
          "";
        if (isStopKeyword(text)) {
          const senderPhone = normalizePhone(remoteJid.split("@")[0]);
          if (senderPhone && !optedOutPhones.has(senderPhone)) {
            optedOutPhones.add(senderPhone);
            saveOptOuts(optedOutPhones);
            try {
              await sock.sendMessage(remoteJid, {
                text: "✅ Votre demande est bien prise en compte. Vous ne recevrez plus de messages promotionnels de Baba Market.",
              });
            } catch (_err) {
              // ignore
            }
          }
        }
      }
    });
  } finally {
    isConnecting = false;
  }
}

// ---------------------------------------------------------------------------
// Middleware clé API (optionnel si BABA_WHATSAPP_API_KEY est défini)
// ---------------------------------------------------------------------------
function requireApiKey(req, res, next) {
  if (!API_KEY) return next();
  const bearer = String(req.headers.authorization || "").replace(/^Bearer\s+/i, "").trim();
  const headerKey = String(req.headers["x-api-key"] || "").trim();
  if (bearer === API_KEY || headerKey === API_KEY) return next();
  return res.status(401).json({ success: false, error: "unauthorized" });
}

// ---------------------------------------------------------------------------
// Routes existantes
// ---------------------------------------------------------------------------
function statusHandler(_req, res) {
  return res.json({
    status: connectionStatus,
    connected: connectionStatus === "connected",
    qr: connectionStatus === "qr_ready" ? latestQrDataUri : null,
    phone: connectedPhone,
  });
}

app.get(["/api/status", "/status", "/health"], requireApiKey, statusHandler);

app.post("/api/send", requireApiKey, async (req, res) => {
  if (!sock || connectionStatus !== "connected") {
    return res.status(503).json({ sent: false, error: "not_connected" });
  }
  const rawPhone = req.body.phone || req.body.number;
  const text = String(req.body.message || req.body.text || "").trim();
  const jid = toJid(rawPhone);
  if (!jid || !text) {
    return res.status(400).json({ sent: false, error: "invalid_payload" });
  }
  try {
    await sock.sendMessage(jid, { text });
    return res.json({ sent: true, phone: normalizePhone(rawPhone) });
  } catch (err) {
    return res.status(500).json({ sent: false, error: String(err && err.message ? err.message : err) });
  }
});

async function logoutHandler(_req, res) {
  try {
    if (sock) {
      try {
        await sock.logout();
      } catch (_err) {
        // ignore
      }
      try {
        sock.end();
      } catch (_err) {
        // ignore
      }
      sock = null;
    }
    fs.rmSync(AUTH_DIR, { recursive: true, force: true });
    connectionStatus = "disconnected";
    latestQrDataUri = null;
    connectedPhone = null;
    setTimeout(() => startSocket(), 800);
    return res.json({ success: true, message: "Session déconnectée et réinitialisée." });
  } catch (err) {
    return res.status(500).json({ success: false, error: String(err) });
  }
}

app.post(["/api/logout", "/logout", "/api/disconnect", "/disconnect"], requireApiKey, logoutHandler);

async function reconnectHandler(_req, res) {
  try {
    if (sock) {
      try {
        sock.end();
      } catch (_err) {
        // ignore
      }
      sock = null;
    }
    connectionStatus = "disconnected";
    await startSocket();
    return res.json({ success: true, message: "Reconnexion lancée." });
  } catch (err) {
    return res.status(500).json({ success: false, error: String(err) });
  }
}

app.post(["/api/reconnect", "/reconnect", "/api/qr/refresh"], requireApiKey, reconnectHandler);

// ---------------------------------------------------------------------------
// Nouveaux endpoints : Statut 24h & Diffusion (Groupes & Clients)
// ---------------------------------------------------------------------------
app.post("/api/groups/resolve", requireApiKey, async (req, res) => {
  if (!sock || connectionStatus !== "connected") {
    return res.status(503).json({ ok: false, error: "not_connected" });
  }
  const linkOrJid = String(req.body.link || req.body.target || "").trim();
  const info = await resolveTargetJid(linkOrJid);
  if (!info || !info.isGroup) {
    return res.status(400).json({ ok: false, error: "not_a_valid_group" });
  }
  return res.json({ ok: true, jid: info.jid, name: info.label });
});

app.post("/api/promo/status", requireApiKey, async (req, res) => {
  if (!sock || connectionStatus !== "connected") {
    return res.status(503).json({ ok: false, error: "not_connected" });
  }
  const imageUrl = String(req.body.image_url || "").trim();
  const caption = String(req.body.caption || "").trim();
  if ((!imageUrl && !req.body.image_base64) || !caption) {
    return res.status(400).json({ ok: false, error: "invalid_status_payload" });
  }
  const rawList = Array.isArray(req.body.status_jid_list) ? req.body.status_jid_list : [];
  const statusJidList = [
    ...new Set([
      ...rawList.map(toJid).filter(Boolean),
      ...knownContacts,
    ]),
  ];
  if (connectedPhone) {
    statusJidList.push(`${connectedPhone}@s.whatsapp.net`);
  }

  let buffer = null;
  // 1. Décodage instantané depuis image_base64 (zéro requête HTTP externe ou interne)
  if (req.body.image_base64) {
    try {
      const cleanBase64 = String(req.body.image_base64).replace(/^data:image\/[a-zA-Z0-9+.-]+;base64,/, "").trim();
      if (cleanBase64) {
        buffer = Buffer.from(cleanBase64, "base64");
      }
    } catch (b64Err) {
      logger.warn({ err: b64Err?.message }, "Impossible de décoder image_base64 pour le statut");
      buffer = null;
    }
  }

  // 2. Repli éventuel sur URL si base64 non fourni
  if (!buffer && imageUrl) {
    try {
      buffer = await fetchImageBuffer(imageUrl);
    } catch (imgErr) {
      logger.warn({ err: imgErr?.message, imageUrl }, "Impossible de télécharger l'image pour le statut");
    }
  }

  if (!buffer) {
    logger.error({ imageUrl }, "Échec de récupération de l'image pour le statut 24h");
    return res.status(502).json({ ok: false, error: "image_unavailable", detail: "Impossible d'obtenir l'image du produit pour le statut" });
  }

  try {
    const finalJids = [...new Set(statusJidList)];
    const options = {
      broadcast: true,
      ...(finalJids.length > 0 ? { statusJidList: finalJids } : {}),
    };
    await sock.sendMessage("status@broadcast", { image: buffer, caption, mimetype: "image/jpeg" }, options);
    return res.json({ ok: true, recipients: finalJids.length });
  } catch (err) {
    return res.status(500).json({ ok: false, error: String(err && err.message ? err.message : err) });
  }
});

app.post("/api/promo/send-media", requireApiKey, async (req, res) => {
  if (!sock || connectionStatus !== "connected") {
    return res.status(503).json({ ok: false, error: "not_connected" });
  }
  const target = req.body.target || req.body.phone || req.body.group;
  const imageUrl = String(req.body.image_url || "").trim();
  const caption = String(req.body.caption || "").trim();
  const requiresImage = Boolean(req.body.has_image || req.body.image_url || req.body.image_base64);

  if (!target || (!imageUrl && !req.body.image_base64 && !caption) || !caption) {
    return res.status(400).json({ ok: false, error: "invalid_media_payload" });
  }

  const targetInfo = await resolveTargetJid(target);
  if (!targetInfo) {
    return res.status(400).json({ ok: false, error: "invalid_target" });
  }

  // Si c'est un message direct vers un client
  if (!targetInfo.isGroup) {
    if (optedOutPhones.has(targetInfo.phone)) {
      return res.status(409).json({ ok: false, error: "opted_out", phone: targetInfo.phone });
    }
    try {
      const check = await sock.onWhatsApp(targetInfo.jid);
      const exists = Array.isArray(check) && check[0] && check[0].exists;
      if (!exists) {
        return res.status(404).json({ ok: false, error: "not_on_whatsapp", phone: targetInfo.phone });
      }
    } catch (_checkErr) {
      // ignore
    }
  }

  let buffer = null;
  // 1. Décodage immédiat en mémoire si image_base64 est fourni (rapide, zéro requête réseau)
  if (req.body.image_base64) {
    try {
      const cleanBase64 = String(req.body.image_base64).replace(/^data:image\/[a-zA-Z0-9+.-]+;base64,/, "").trim();
      if (cleanBase64) {
        buffer = Buffer.from(cleanBase64, "base64");
        if (buffer.length === 0 || buffer.length > MAX_IMAGE_BYTES) {
          logger.warn({ size: buffer.length }, "Taille image_base64 invalide");
          buffer = null;
        }
      }
    } catch (b64Err) {
      logger.warn({ err: b64Err?.message }, "Impossible de décoder image_base64");
      buffer = null;
    }
  }

  // 2. Repli éventuel sur téléchargement URL si pas de base64
  if (!buffer && imageUrl) {
    try {
      buffer = await fetchImageBuffer(imageUrl);
    } catch (imgErr) {
      logger.warn({ err: imgErr?.message, imageUrl }, "Impossible de télécharger l'image via URL");
    }
  }

  // RÈGLE STRICTE : Si le produit a une photo rattachée, elle DOIT être envoyée avec l'image !
  // On ne diffuse JAMAIS de message tronqué sans image si une image est requise.
  if (requiresImage && !buffer) {
    logger.error({ target: targetInfo.jid, imageUrl }, "Échec de récupération de l'image requise");
    return res.status(502).json({ ok: false, error: "image_unavailable", detail: "Image obligatoire introuvable ou inaccessible" });
  }

  try {
    // Simulation présence humaine (anti-ban)
    try {
      await sock.sendPresenceUpdate("composing", targetInfo.jid);
      await sleep(1000 + Math.floor(Math.random() * 1000));
      await sock.sendPresenceUpdate("paused", targetInfo.jid);
    } catch (_err) {
      // ignore
    }

    if (buffer) {
      await sock.sendMessage(targetInfo.jid, { image: buffer, caption, mimetype: "image/jpeg" });
    } else {
      await sock.sendMessage(targetInfo.jid, { text: caption });
    }

    logger.info({ target: targetInfo.jid, label: targetInfo.label, hasImage: !!buffer }, "Message diffusé avec succès");
    return res.json({
      ok: true,
      target: targetInfo.jid,
      isGroup: targetInfo.isGroup,
      label: targetInfo.label,
      imageSent: !!buffer,
    });
  } catch (sendErr) {
    logger.error({ err: sendErr, target: targetInfo.jid }, "Erreur sendMessage");
    return res.status(500).json({ ok: false, error: String(sendErr && sendErr.message ? sendErr.message : sendErr) });
  }
});

app.listen(PORT, HOST, () => {
  startSocket();
});

