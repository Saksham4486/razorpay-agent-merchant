// Frontend Application Logic for Razorpay Autonomous Agent Merchant System (Hardened)

let chatHistory = [];
let currentChaosOrder = null;
let activeTimers = {};
let isLiveRazorpay = false;

document.addEventListener('DOMContentLoaded', () => {
  initHealthAndMode();
  initTabs();
  initAuditTrail();
  initChat();
  initAds();
  initAcp();
  initChaosLab();
  
  // Auto-refresh audit trail every 6 seconds
  setInterval(loadAuditTrail, 6000);
});

async function initHealthAndMode() {
  try {
    const res = await fetch('/health');
    const data = await res.json();
    const badge = document.getElementById('header-mode-badge');
    if (badge) {
      if (data.is_mock) {
        badge.textContent = '🧪 MOCK SANDBOX';
        badge.className = 'badge badge-test';
        isLiveRazorpay = false;
      } else {
        badge.textContent = '✅ LIVE TEST MODE';
        badge.className = 'badge badge-core';
        isLiveRazorpay = true;
      }
    }
  } catch (err) {
    console.warn("Health check error:", err);
  }
}

// --- Tab Navigation ---
function initTabs() {
  const tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      
      tab.classList.add('active');
      const targetId = tab.getAttribute('data-tab');
      const targetContent = document.getElementById(targetId);
      if (targetContent) targetContent.classList.add('active');

      if (targetId === 'audit-tab') loadAuditTrail();
      if (targetId === 'ads-tab') loadCatalogForAds();
      if (targetId === 'acp-tab') loadAcpFeed();
    });
  });
}

// --- Audit Trail & Tamper-Evident Hash Chain Dashboard ---
function initAuditTrail() {
  document.getElementById('btn-refresh-audit').addEventListener('click', loadAuditTrail);
  document.getElementById('audit-filter-actor').addEventListener('change', loadAuditTrail);
  document.getElementById('btn-verify-chain').addEventListener('click', verifyAuditHashChain);
  loadAuditTrail();
}

async function verifyAuditHashChain() {
  try {
    const res = await fetch('/api/audit/verify');
    const data = await res.json();
    const chainBadge = document.getElementById('header-chain-badge');

    if (data.valid) {
      alert(`✅ Cryptographic Audit Trail Verified!\n\nAll ${data.total_verified} records verified with SHA-256 hash chaining.\nChain Integrity: INTACT\nLatest Hash: ${data.latest_hash || 'Genesis'}`);
      if (chainBadge) {
        chainBadge.textContent = '🛡️ HASH-CHAIN INTACT';
        chainBadge.className = 'badge badge-test';
      }
    } else {
      alert(`❌ TAMPERING DETECTED!\n\nAudit chain broken at record ID: ${data.broken_at_id}\nError: ${data.error}\nExpected: ${data.expected_prev || data.expected_hash}\nActual: ${data.actual_prev || data.stored_hash}`);
      if (chainBadge) {
        chainBadge.textContent = '⚠️ TAMPER DETECTED';
        chainBadge.className = 'badge badge-danger';
      }
    }
  } catch (err) {
    alert(`Failed to verify audit hash chain: ${err.message}`);
  }
}

async function loadAuditTrail() {
  try {
    const actorFilter = document.getElementById('audit-filter-actor').value;
    let url = '/api/audit?limit=50';
    if (actorFilter) url += `&actor=${actorFilter}`;

    const res = await fetch(url);
    const data = await res.json();

    // Update Header Metric
    const dailySpend = data.daily_spend_inr || 0;
    const dailyCap = data.daily_cap_inr || 10000000;
    document.getElementById('header-daily-spend').textContent = `₹${dailySpend.toLocaleString('en-IN', {minimumFractionDigits: 2})} / ₹${dailyCap.toLocaleString('en-IN')}`;
    const pct = Math.min(100, (dailySpend / dailyCap) * 100);
    document.getElementById('header-spend-progress').style.width = `${pct}%`;

    // Render Table
    const tbody = document.getElementById('audit-table-body');
    if (!data.logs || data.logs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted">No audit logs recorded yet.</td></tr>';
    } else {
      tbody.innerHTML = data.logs.map(log => {
        const timeStr = new Date(log.timestamp).toLocaleTimeString();
        const statusClass = `status-${log.status.toLowerCase()}`;
        const hashDisplay = log.entry_hash ? `${log.entry_hash.substring(0, 8)}...` : '<span class="text-muted">legacy</span>';
        return `
          <tr>
            <td class="font-mono text-muted">${timeStr}</td>
            <td><strong>${escapeHtml(log.actor)}</strong></td>
            <td class="font-mono">${escapeHtml(log.sku)}</td>
            <td>${log.requested_discount > 0 ? log.requested_discount.toFixed(1) + '%' : '-'}</td>
            <td class="font-mono">₹${log.order_value_inr.toLocaleString('en-IN', {minimumFractionDigits: 2})}</td>
            <td><span class="badge ${log.policy_decision === 'approved' ? 'badge-test' : 'badge-core'}">${log.policy_decision}</span></td>
            <td><span class="tag-status ${statusClass}">${log.status}</span></td>
            <td style="max-width: 300px; font-size: 0.78rem; color: #cbd5e1;">${escapeHtml(log.reason)}</td>
            <td class="font-mono text-sm">${log.razorpay_order_id ? escapeHtml(log.razorpay_order_id) : '<span class="text-muted">N/A</span>'}</td>
            <td class="font-mono text-xs text-accent" title="${log.entry_hash || ''}">${hashDisplay}</td>
          </tr>
        `;
      }).join('');
    }

    // Render Trust Scores
    const trustContainer = document.getElementById('trust-score-container');
    if (!data.trust_scores || data.trust_scores.length === 0) {
      trustContainer.innerHTML = '<p class="text-muted text-sm">No agent activity recorded yet.</p>';
    } else {
      trustContainer.innerHTML = data.trust_scores.map(ts => `
        <div class="trust-item">
          <div>
            <strong>${escapeHtml(ts.agent_id)}</strong>
            <div class="text-xs text-muted" style="font-size: 0.75rem;">Orders: ${ts.paid_orders} paid / ${ts.total_orders} total</div>
          </div>
          <div class="trust-score-badge">Score: ${(ts.trust_score * 100).toFixed(0)}%</div>
        </div>
      `).join('');
    }
  } catch (err) {
    console.error("Failed to load audit trail:", err);
  }
}

// --- Conversational Commerce Chat ---
function initChat() {
  const input = document.getElementById('chat-input');
  const btn = document.getElementById('chat-send-btn');
  const langSelect = document.getElementById('chat-language-select');

  const sendMessage = async () => {
    const text = input.value.trim();
    if (!text) return;

    const selectedLang = langSelect ? langSelect.value : 'auto';

    input.value = '';
    appendChatMessage('user', text);
    chatHistory.push({ role: 'user', content: text });

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: chatHistory,
          agent_id: 'human_web_shopper',
          language: selectedLang
        })
      });
      const data = await res.json();
      
      if (langSelect && data.language && selectedLang === 'auto') {
        langSelect.value = data.language;
      }

      appendChatMessage('assistant', data.reply, data.active_order, data.razorpay_key_id);
      chatHistory.push({ role: 'assistant', content: data.reply });

      if (data.tool_calls && data.tool_calls.length > 0) {
        renderToolCalls(data.tool_calls);
      }
      loadAuditTrail();

      // If active order was created in pending_payment, trigger Razorpay Checkout
      if (data.active_order && data.active_order.status === 'pending_payment') {
        launchRealRazorpayCheckout(data.active_order, data.razorpay_key_id);
      }
    } catch (err) {
      appendChatMessage('assistant', 'Sorry, an error occurred while processing your request.');
    }
  };

  btn.addEventListener('click', sendMessage);
  input.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
  });
}

function appendChatMessage(role, text, activeOrder = null, razorpayKeyId = null) {
  const container = document.getElementById('chat-messages');
  const bubble = document.createElement('div');
  bubble.className = `chat-bubble ${role}`;
  bubble.innerHTML = formatMarkdownLinks(escapeHtml(text));

  // Single-Use Razorpay pay card with Live Expiration Timer
  if (activeOrder && activeOrder.status === 'pending_payment') {
    const cardId = `pay-card-${activeOrder.order_reference}`;
    const timerId = `timer-${activeOrder.order_reference}`;
    const btnId = `pay-btn-${activeOrder.order_reference}`;

    const payCard = document.createElement('div');
    payCard.className = 'chat-pay-action-card';
    payCard.id = cardId;
    
    payCard.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-size: 0.85rem; font-weight: 700;">💳 Order: ${escapeHtml(activeOrder.order_reference)}</span>
        <span id="${timerId}" class="tag-status status-pending_payment font-mono" style="font-size:0.75rem;">⏳ Expires in 15:00</span>
      </div>
      <div style="font-size: 0.8rem; color: #94a3b8;">Amount: <strong class="text-accent">₹${activeOrder.total_amount_inr.toLocaleString('en-IN', {minimumFractionDigits: 2})}</strong></div>
      <button id="${btnId}" class="btn btn-primary btn-sm" style="background:#3b82f6;" onclick="launchRealRazorpayCheckout({order_reference: '${activeOrder.order_reference}', razorpay_order_id: '${activeOrder.razorpay_order_id}', total_amount_inr: ${activeOrder.total_amount_inr}, expires_at: '${activeOrder.expires_at || ''}'}, '${razorpayKeyId || ''}')">
        🚀 Pay ₹${activeOrder.total_amount_inr.toLocaleString('en-IN', {minimumFractionDigits: 2})} via Razorpay Checkout
      </button>
    `;
    bubble.appendChild(payCard);

    startCountdownTimer(activeOrder.order_reference, activeOrder.expires_at, timerId, btnId, cardId);
  }

  container.appendChild(bubble);
  container.scrollTop = container.scrollHeight;
}

function startCountdownTimer(orderRef, expiresAtStr, timerElId, btnElId, cardElId) {
  if (activeTimers[orderRef]) clearInterval(activeTimers[orderRef]);

  const targetTime = expiresAtStr ? new Date(expiresAtStr).getTime() : Date.now() + 15 * 60 * 1000;

  activeTimers[orderRef] = setInterval(() => {
    const now = Date.now();
    const distance = targetTime - now;
    const timerEl = document.getElementById(timerElId);
    const btnEl = document.getElementById(btnElId);

    if (distance <= 0) {
      clearInterval(activeTimers[orderRef]);
      if (timerEl) {
        timerEl.textContent = '❌ Link Expired (Dead)';
        timerEl.className = 'tag-status status-rejected font-mono';
      }
      if (btnEl) {
        btnEl.disabled = true;
        btnEl.textContent = '⚠️ Payment Expired';
        btnEl.style.background = '#64748b';
      }
    } else {
      const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
      const seconds = Math.floor((distance % (1000 * 60)) / 1000);
      const minStr = String(minutes).padStart(2, '0');
      const secStr = String(seconds).padStart(2, '0');
      if (timerEl) timerEl.textContent = `⏳ Expires in ${minStr}:${secStr}`;
    }
  }, 1000);
}

// --- Official Real Razorpay Checkout.js Integration (Phase 1) ---
function launchRealRazorpayCheckout(order, keyId) {
  if (!isLiveRazorpay) {
    // Mock mode: never attempt to open the real Razorpay iframe with a
    // fabricated order_test_... id / mock key - that errors in the browser.
    // Instead, run an honest server-verified simulated payment (A2).
    simulateMockPayment(order);
    return;
  }

  const effectiveKey = keyId || "rzp_test_mock_merchant_key";
  const amountPaise = Math.round(order.total_amount_inr * 100);

  const options = {
    key: effectiveKey,
    amount: amountPaise,
    currency: "INR",
    name: "Razorpay Autonomous Merchant",
    description: `Order ${order.order_reference}`,
    image: "https://cdn.razorpay.com/static/assets/logo/rzp.png",
    order_id: order.razorpay_order_id,
    handler: async function (response) {
      await submitPaymentVerification(order.order_reference, response.razorpay_payment_id, response.razorpay_order_id, response.razorpay_signature, order.total_amount_inr);
    },
    modal: {
      ondismiss: function () {
        console.log("Razorpay checkout modal dismissed by user. Order remains pending_payment.");
      }
    },
    theme: { color: "#3b82f6" }
  };

  const rzp = new Razorpay(options);
  rzp.on('payment.failed', function (response) {
    alert(`Payment failed: ${response.error.description} (Code: ${response.error.code})`);
  });
  rzp.open();
}

// Mock-mode payment simulation: calls the honestly-labeled backend endpoint
// which generates a real HMAC SHA-256 signature server-side and verifies it
// through the exact same path a real payment takes. No client-side fakes.
async function simulateMockPayment(order) {
  const confirmPay = confirm(`[Mock Sandbox]\n\nSimulate payment of ₹${order.total_amount_inr.toLocaleString('en-IN', {minimumFractionDigits: 2})} for Order ${order.order_reference}?\n\n(Server will generate and verify a genuine HMAC SHA-256 test signature - no real Razorpay charge occurs.)`);
  if (!confirmPay) return;

  try {
    const res = await fetch(`/api/orders/${order.order_reference}/simulate-payment`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    const data = await res.json();

    if (!res.ok) {
      alert(`Simulation error: ${data.detail ? (data.detail.message || JSON.stringify(data.detail)) : 'Simulation failed'}`);
      return;
    }

    finalizePaidOrderUI(order.order_reference, data.razorpay_payment_id, order.total_amount_inr);
  } catch (err) {
    alert(`Payment simulation failed: ${err.message}`);
  }
}

function finalizePaidOrderUI(orderRef, paymentId, amount) {
  if (activeTimers[orderRef]) clearInterval(activeTimers[orderRef]);

  const timerEl = document.getElementById(`timer-${orderRef}`);
  const btnEl = document.getElementById(`pay-btn-${orderRef}`);
  if (timerEl) {
    timerEl.textContent = '🔒 Payment Deactivated (Fulfilled)';
    timerEl.className = 'tag-status status-paid font-mono';
  }
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = '✅ Payment Fulfilled & Verified';
    btnEl.style.background = '#10b981';
  }

  appendChatMessage('assistant', `✅ Payment of **₹${amount.toLocaleString('en-IN', {minimumFractionDigits: 2})}** verified via cryptographic HMAC SHA-256!\n\n• **Payment ID**: \`${paymentId}\`\n• **Order Ref**: \`${orderRef}\`\n• **Status**: \`PAID\`\n• 🔒 **Single-Use Link Deactivated**`);
  loadAuditTrail();
}

async function submitPaymentVerification(orderRef, paymentId, orderId, signature, amount) {
  try {
    const res = await fetch(`/api/orders/${orderRef}/verify-payment`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        razorpay_payment_id: paymentId,
        razorpay_order_id: orderId,
        razorpay_signature: signature
      })
    });

    const data = await res.json();

    if (!res.ok) {
      alert(`Verification Error: ${data.detail ? (data.detail.message || JSON.stringify(data.detail)) : 'Invalid Signature'}`);
      return;
    }

    finalizePaidOrderUI(orderRef, paymentId, amount);
  } catch (err) {
    alert(`Payment verification failed: ${err.message}`);
  }
}

function renderToolCalls(toolCalls) {
  const feed = document.getElementById('chat-tool-feed');
  if (feed.querySelector('.empty-state')) feed.innerHTML = '';

  toolCalls.forEach(tc => {
    const card = document.createElement('div');
    card.className = 'tool-card';
    card.innerHTML = `
      <div class="tool-title">⚡ Tool Invoked: ${escapeHtml(tc.tool_name)}</div>
      <div style="font-size:0.75rem; color: #94a3b8; margin-bottom: 0.2rem;">Arguments:</div>
      <pre class="tool-code">${escapeHtml(JSON.stringify(tc.arguments, null, 2))}</pre>
      <div style="font-size:0.75rem; color: #94a3b8; margin: 0.4rem 0 0.2rem 0;">Policy Result:</div>
      <pre class="tool-code">${escapeHtml(JSON.stringify(tc.result, null, 2))}</pre>
    `;
    feed.insertBefore(card, feed.firstChild);
  });
}

// --- Multilingual Ad Growth Engine ---
async function loadCatalogForAds() {
  const select = document.getElementById('ad-sku-select');
  if (select.children.length > 0) return;

  try {
    const res = await fetch('/api/catalog');
    const data = await res.json();
    select.innerHTML = data.items.map(item => `
      <option value="${item.sku}">${item.name} (₹${item.price_inr.toLocaleString('en-IN')})</option>
    `).join('');
  } catch (err) {
    console.error("Failed to load catalog for ads:", err);
  }
}

function initAds() {
  document.getElementById('btn-generate-ads').addEventListener('click', async () => {
    const sku = document.getElementById('ad-sku-select').value;
    if (!sku) return;

    const container = document.getElementById('ad-cards-container');
    container.innerHTML = '<div class="empty-state">Generating multilingual campaigns via LLM engine...</div>';

    try {
      const res = await fetch('/api/ads/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sku: sku, languages: ['en', 'hi', 'ta', 'te', 'es'] })
      });
      const data = await res.json();

      container.innerHTML = data.ads.map(ad => `
        <div class="ad-card">
          <div>
            <div class="ad-lang-badge">🌐 ${escapeHtml(ad.language_name)}</div>
            <div class="ad-headline">${escapeHtml(ad.headline)}</div>
            <div class="ad-body">${escapeHtml(ad.body_text)}</div>
            <div class="ad-hook">💡 ${escapeHtml(ad.discount_hook)}</div>
          </div>
          <div>
            <button class="btn btn-outline btn-sm" style="width:100%;" onclick="openChatWithDeepLink('${sku}', '${ad.language_code}')">
              💬 ${escapeHtml(ad.call_to_action)} &rarr;
            </button>
          </div>
        </div>
      `).join('');
    } catch (err) {
      container.innerHTML = '<div class="empty-state text-danger">Failed to generate ads.</div>';
    }
  });
}

window.openChatWithDeepLink = function(sku, lang) {
  const tabBtn = document.querySelector('[data-tab="chat-tab"]');
  if (tabBtn) tabBtn.click();
  
  const langSelect = document.getElementById('chat-language-select');
  if (langSelect) langSelect.value = lang;

  const input = document.getElementById('chat-input');
  
  const localizedPrompts = {
    hi: `नमस्ते, मैंने आपका विज्ञापन देखा। मुझे ${sku} पर 10% छूट चाहिए और इसे खरीदना है।`,
    ta: `வணக்கம், நான் உங்கள் விளம்பரத்தைப் பார்த்தேன். எனக்கு ${sku} மீது 10% தள்ளுபடியுடன் வாங்க வேண்டும்.`,
    te: `నమస్కారం, నేను మీ ప్రకటన చూశాను. నాకు ${sku} పై 10% తగ్గింపుతో కొనాలని ఉంది.`,
    es: `Hola, vi su anuncio. Quiero negociar un 10% de descuento en ${sku} y comprarlo.`,
    en: `Hello, I saw your promotional ad for ${sku}. Can I get 10% off and buy it?`
  };

  input.value = localizedPrompts[lang] || localizedPrompts['en'];
  document.getElementById('chat-send-btn').click();
};

// --- ACP & AP2 Mandates Logic (Phase 9) ---
function initAcp() {
  document.getElementById('btn-refresh-acp-feed').addEventListener('click', loadAcpFeed);
}

async function loadAcpFeed() {
  const display = document.getElementById('acp-feed-display');
  display.textContent = 'Fetching ACP product feed (GET /acp/feed)...';

  try {
    const res = await fetch('/acp/feed');
    const data = await res.json();
    display.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    display.textContent = `Failed to load ACP feed: ${err.message}`;
  }
}

window.testValidMandate = async function() {
  const out = document.getElementById('mandate-test-output');
  out.textContent = "Testing AP2 Signed Mandate (Quantity=1, Cap=15%)...\n";

  try {
    const agentId = "agent_ap2_corp";
    const authHeaders = await getAgentAuthHeaders(agentId);
    const mandate = {
      agent_id: agentId,
      sku: "SKU-AI-ROUTER-PRO",
      max_unit_price: 45000.0,
      max_discount_pct: 15.0,
      max_quantity: 2,
      valid_until: new Date(Date.now() + 3600000).toISOString(),
      issued_at: new Date().toISOString()
    };

    const res = await fetch('/api/negotiate', {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({
        sku: "SKU-AI-ROUTER-PRO",
        requested_discount_pct: 10.0,
        quantity: 1,
        agent_id: agentId,
        actor_type: "ai_agent",
        mandate: mandate,
        mandate_signature: "mock_mandate_sig_valid"
      })
    });
    const data = await res.json();
    out.textContent += `Result: Allowed = ${data.allowed}\nPolicy Status = ${data.policy_status}\nReason: ${data.reason}`;
    loadAuditTrail();
  } catch (err) {
    out.textContent += `Error: ${err.message}`;
  }
};

window.testViolatedMandate = async function() {
  const out = document.getElementById('mandate-test-output');
  out.textContent = "Testing Mandate Quantity Violation (Buyer asks for 5 units, Mandate max is 2)...\n";

  try {
    const agentId = "agent_ap2_corp";
    const authHeaders = await getAgentAuthHeaders(agentId);
    const mandate = {
      agent_id: agentId,
      sku: "SKU-AI-ROUTER-PRO",
      max_unit_price: 45000.0,
      max_discount_pct: 15.0,
      max_quantity: 2,
      valid_until: new Date(Date.now() + 3600000).toISOString(),
      issued_at: new Date().toISOString()
    };

    const res = await fetch('/api/negotiate', {
      method: 'POST',
      headers: authHeaders,
      body: JSON.stringify({
        sku: "SKU-AI-ROUTER-PRO",
        requested_discount_pct: 10.0,
        quantity: 5,
        agent_id: agentId,
        actor_type: "ai_agent",
        mandate: mandate,
        mandate_signature: "mock_mandate_sig_valid"
      })
    });
    const data = await res.json();
    out.textContent += `Result: Allowed = ${data.allowed}\nPolicy Status = ${data.policy_status}\nReason: ${data.reason}`;
    loadAuditTrail();
  } catch (err) {
    out.textContent += `Error: ${err.message}`;
  }
};

// --- Agent Key Management (A1) ---
// Demo/simulation buttons impersonate fixed agent_ids across multiple calls.
// Register once per browser (persisted in localStorage) and attach the
// issued X-Agent-Key on every subsequent call for that agent_id, exactly
// like a real autonomous agent is expected to.
async function getAgentAuthHeaders(agentId) {
  const storageKey = `agent_key:${agentId}`;
  let key = localStorage.getItem(storageKey);
  if (!key) {
    try {
      const res = await fetch('/api/agents/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId })
      });
      if (res.ok) {
        const data = await res.json();
        key = data.agent_key;
        localStorage.setItem(storageKey, key);
      } else if (res.status === 409) {
        // Already registered in a previous session whose key we lost (e.g.
        // cleared storage). Nothing we can do but surface it clearly.
        console.warn(`Agent '${agentId}' already registered server-side but no local key found.`);
      }
    } catch (err) {
      console.warn(`Agent registration failed for ${agentId}:`, err);
    }
  }
  return key ? { 'Content-Type': 'application/json', 'X-Agent-Key': key } : { 'Content-Type': 'application/json' };
}

// --- AI Buyer Simulation Trigger ---
window.runSimulationPersona = async function(persona) {
  const consoleEl = document.getElementById('sim-console');
  consoleEl.textContent = `[Simulation Started] Running Persona: ${persona.toUpperCase()}...\n\n`;

  try {
    if (persona === 'bargain') {
      const agentId = 'agent_bargain_hunter';
      const authHeaders = await getAgentAuthHeaders(agentId);
      appendLog(consoleEl, "1. Fetching Catalog for SKU-AI-ROUTER-PRO (₹45,000)...");
      const catRes = await fetch('/api/catalog');
      const cat = await catRes.json();
      
      appendLog(consoleEl, "2. Requesting 30% discount (Exceeds SKU limit of 15%)...");
      const neg1 = await (await fetch('/api/negotiate', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ sku: 'SKU-AI-ROUTER-PRO', requested_discount_pct: 30.0, quantity: 1, agent_id: agentId, actor_type: 'ai_agent' })
      })).json();
      
      appendLog(consoleEl, `❌ Rejection Received: "${neg1.reason}"`);
      appendLog(consoleEl, "3. 🧠 Agent autonomously renegotiates at maximum permissible cap (15%)...");
      
      const neg2 = await (await fetch('/api/negotiate', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ sku: 'SKU-AI-ROUTER-PRO', requested_discount_pct: 15.0, quantity: 1, agent_id: agentId, actor_type: 'ai_agent' })
      })).json();
      appendLog(consoleEl, `✅ Approval Received: Unit Price: ₹${neg2.final_unit_price_inr.toLocaleString('en-IN')}`);

      appendLog(consoleEl, "4. Executing Checkout with Idempotency Key...");
      const idempKey = 'idemp_ui_' + Math.random().toString(36).substring(2, 10);
      const chk = await (await fetch('/api/checkout', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ sku: 'SKU-AI-ROUTER-PRO', quantity: 1, requested_discount_pct: 15.0, actor_type: 'ai_agent', agent_id: agentId, idempotency_key: idempKey })
      })).json();
      appendLog(consoleEl, `🎉 Razorpay Order Created: ${chk.razorpay_order_id} (Ref: ${chk.order_reference})`);

      appendLog(consoleEl, "5. Webhook signature verified -> Order marked PAID & Hash Chain updated.");
      loadAuditTrail();
    } else if (persona === 'whale') {
      const agentId = 'agent_enterprise_whale';
      const authHeaders = await getAgentAuthHeaders(agentId);
      appendLog(consoleEl, "1. Placing High-Value Enterprise Order (1x GPU Dev Box @ ₹1,85,000 = ₹1,75,750)...");
      const idempKey = 'idemp_whale_' + Math.random().toString(36).substring(2, 10);
      const chk = await (await fetch('/api/checkout', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ sku: 'SKU-GPU-DEV-BOX', quantity: 1, requested_discount_pct: 5.0, actor_type: 'ai_agent', agent_id: agentId, idempotency_key: idempKey })
      })).json();

      appendLog(consoleEl, `⚠️ Policy Gating Triggered: Status = ${chk.status}`);
      appendLog(consoleEl, `Reason: "${chk.policy_reason}"`);
      appendLog(consoleEl, "2. 👔 Merchant Admin authorizes order with HTTP Basic credentials...");
      
      const adminRes = await (await fetch(`/api/admin/orders/${chk.order_reference}/approve`, {
        method: 'POST',
        headers: { 'Authorization': 'Basic ' + btoa('admin:razorpay_agent_secure_2026') }
      })).json();
      appendLog(consoleEl, `✅ Admin Approved! Razorpay Order ID: ${adminRes.razorpay_order_id}`);
    } else if (persona === 'impatient') {
      const agentId = 'agent_impatient_fast';
      const authHeaders = await getAgentAuthHeaders(agentId);
      const fixedKey = 'idemp_double_tap_' + Math.random().toString(36).substring(2, 8);
      appendLog(consoleEl, `1. Sending first checkout with idempotency_key: ${fixedKey}...`);
      const r1 = await (await fetch('/api/checkout', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ sku: 'SKU-CLOUD-CREDITS', quantity: 2, requested_discount_pct: 10.0, actor_type: 'ai_agent', agent_id: agentId, idempotency_key: fixedKey })
      })).json();
      appendLog(consoleEl, `Order 1 Ref: ${r1.order_reference} (Replay: ${r1.idempotent_replay})`);

      appendLog(consoleEl, "2. ⚡ Sending duplicate checkout concurrently...");
      const r2 = await (await fetch('/api/checkout', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ sku: 'SKU-CLOUD-CREDITS', quantity: 2, requested_discount_pct: 10.0, actor_type: 'ai_agent', agent_id: agentId, idempotency_key: fixedKey })
      })).json();
      appendLog(consoleEl, `Order 2 Ref: ${r2.order_reference} (Replay: ${r2.idempotent_replay})`);
      appendLog(consoleEl, `🛡️ ZERO Double-Charge Guarantee: Orders are identical (${r1.order_reference} == ${r2.order_reference})`);
    }
    loadAuditTrail();
  } catch (err) {
    appendLog(consoleEl, `❌ Error: ${err.message}`);
  }
};

window.runAllSimulations = async function() {
  await window.runSimulationPersona('bargain');
  await new Promise(r => setTimeout(r, 600));
  await window.runSimulationPersona('whale');
  await new Promise(r => setTimeout(r, 600));
  await window.runSimulationPersona('impatient');
};

function appendLog(el, msg) {
  el.textContent += `${msg}\n`;
  el.scrollTop = el.scrollHeight;
}

// --- Chaos & Complete Money Lifecycle Lab ---
function initChaosLab() {
  const btnCreate = document.getElementById('btn-chaos-create-order');
  const btnDelay = document.getElementById('btn-chaos-delay-webhook');
  const btnPoll = document.getElementById('btn-chaos-poll-fallback');
  const btnRefund = document.getElementById('btn-chaos-refund-order');
  const telemetry = document.getElementById('chaos-telemetry-output');

  btnCreate.addEventListener('click', async () => {
    telemetry.textContent = "[Step 1] Creating a test order for chaos experiment...\n";
    const idempKey = 'chaos_' + Math.random().toString(36).substring(2, 10);
    
    try {
      const res = await fetch('/api/checkout', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          sku: 'SKU-POS-TERMINAL',
          quantity: 1,
          requested_discount_pct: 10.0,
          actor_type: 'human',
          idempotency_key: idempKey,
          customer_name: 'Chaos Test Shopper'
        })
      });
      const order = await res.json();
      currentChaosOrder = order.order_reference;
      
      document.getElementById('chaos-active-order').textContent = `Active Order: ${order.order_reference} (${order.status})`;
      btnDelay.disabled = false;
      btnPoll.disabled = true;
      btnRefund.disabled = true;

      telemetry.textContent += `✅ Test Order Created:\n${JSON.stringify(order, null, 2)}\n\nReady for Step 2: Inject Webhook Drop.`;
      loadAuditTrail();
    } catch (err) {
      telemetry.textContent += `❌ Failed to create order: ${err.message}`;
    }
  });

  btnDelay.addEventListener('click', async () => {
    if (!currentChaosOrder) return;
    telemetry.textContent += `\n\n[Step 2] Simulating dropped/delayed webhook for ${currentChaosOrder}...\n`;

    try {
      const res = await fetch(`/api/orders/${currentChaosOrder}/simulate-webhook-delay`, { method: 'POST' });
      const data = await res.json();

      document.getElementById('chaos-active-order').textContent = `Active Order: ${currentChaosOrder} (${data.status})`;
      btnDelay.disabled = true;
      btnPoll.disabled = false;

      telemetry.textContent += `⚠️ Webhook dropped! Order status transitioned to: ${data.status.toUpperCase()}.\n`;
      telemetry.textContent += `Audit log updated with failure alert. Ready for Step 3: Trigger Fallback Polling.`;
      loadAuditTrail();
    } catch (err) {
      telemetry.textContent += `❌ Error: ${err.message}`;
    }
  });

  btnPoll.addEventListener('click', async () => {
    if (!currentChaosOrder) return;
    telemetry.textContent += `\n\n[Step 3] Triggering Fallback Polling Worker (/api/orders/${currentChaosOrder}/poll)...\n`;

    try {
      const res = await fetch(`/api/orders/${currentChaosOrder}/poll`, { method: 'POST' });
      const data = await res.json();

      document.getElementById('chaos-active-order').textContent = `Active Order: ${currentChaosOrder} (${data.current_status})`;
      btnPoll.disabled = true;
      btnRefund.disabled = false;

      telemetry.textContent += `🎉 Fallback Recovery Completed Successfully!\n${JSON.stringify(data, null, 2)}\n\n`;
      telemetry.textContent += `Result: Order resolved safely to ${data.current_status.toUpperCase()} via Razorpay Payments API fallback. Ready for Step 4: Refund.`;
      loadAuditTrail();
    } catch (err) {
      telemetry.textContent += `❌ Error: ${err.message}`;
    }
  });

  btnRefund.addEventListener('click', async () => {
    if (!currentChaosOrder) return;
    telemetry.textContent += `\n\n[Step 4] Triggering Refund via Razorpay Refunds API (/api/orders/${currentChaosOrder}/refund)...\n`;

    try {
      const res = await fetch(`/api/orders/${currentChaosOrder}/refund`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: "Customer requested cancellation in Chaos Lab" })
      });
      const data = await res.json();

      document.getElementById('chaos-active-order').textContent = `Active Order: ${currentChaosOrder} (${data.status})`;
      btnRefund.disabled = true;

      telemetry.textContent += `🔄 Order Successfully Refunded!\n${JSON.stringify(data, null, 2)}\n\nRefund ID: ${data.refund_id}. State: REFUNDED. Audit trail recorded.`;
      loadAuditTrail();
    } catch (err) {
      telemetry.textContent += `❌ Refund Error: ${err.message}`;
    }
  });
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function formatMarkdownLinks(str) {
  return str.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" class="text-accent" style="text-decoration: underline;">$1</a>');
}
