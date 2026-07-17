// Shared skeleton-capture fixtures.
//
// Single source of truth for BOTH:
//   - the browser capture harness (tools/capture-bones.html), and
//   - the headless capture automation (see tools/README / DEPLOY.md).
//
// Each fixture provides the *real* card markup and says which page's <style>
// block to load so the card renders exactly as it does in production. The
// capturer mounts `containerOpen + html + containerClose` at 375/768/1280,
// then runs the vendored snapshotBones() on `selector`.
//
// Fidelity notes:
//   - `.reveal` (opacity:0 until observed) is replaced with `.revealed` so the
//     element is visible at capture time.
//   - <iconify-icon> web components need a network script to size themselves,
//     so in fixtures we substitute a same-size inline-block box.

/** A sized stand-in for an <iconify-icon width="N"> (square). */
export function icon(size = 24) {
  return `<span style="display:inline-block;width:${size}px;height:${size}px"></span>`;
}

export const BREAKPOINTS = [375, 768, 1280];

export const FIXTURES = [
  {
    name: 'menu-card',
    page: 'index.html',
    selector: '.menu-card',
    // The 90x90 thumbnail is square, so Boneyard's "squarish media" heuristic
    // renders it as a circle. The real .menu-card-img is a rounded rect
    // (border-radius:8px), so the capturer rewrites that image bone to r:8.
    fixSquareImage: true,
    containerOpen: '<section class="menu-section" style="padding:24px 0"><div class="container"><div class="menu-grid" style="display:grid;grid-template-columns:repeat(3,1fr);gap:20px">',
    containerClose: '</div></div></section>',
    html: `
      <div class="menu-card revealed" style="background:var(--card);border:1px solid var(--border);border-radius:14px;padding:20px;display:flex;gap:16px;position:relative">
        <img class="menu-card-img" src="/static/placeholder.svg" alt="" style="width:90px;height:90px;border-radius:8px;object-fit:cover;flex-shrink:0">
        <div class="menu-card-body" style="flex:1;display:flex;flex-direction:column;gap:6px">
          <div class="menu-card-name" style="font-weight:700;font-size:1rem">Café Latte</div>
          <div class="menu-card-desc" style="font-size:.85rem;color:var(--text-muted)">Espresso with silky steamed milk.</div>
          <div class="menu-card-footer" style="display:flex;align-items:center;justify-content:space-between;margin-top:auto">
            <span class="menu-card-price" style="font-weight:800;color:var(--terracotta)">Rs.179</span>
            <button class="menu-card-add" style="width:36px;height:36px;border-radius:50%;border:1px solid var(--border);background:var(--card);font-size:1.2rem">+</button>
          </div>
        </div>
      </div>`,
  },
  {
    name: 'event-card',
    page: 'index.html',
    selector: '.menu-card',
    containerOpen: '<section class="menu-section" style="padding:24px 0"><div class="container"><div class="menu-grid">',
    containerClose: '</div></div></section>',
    html: `
      <div class="menu-card" style="flex-direction:column">
        <img class="menu-card-img" style="width:100%;height:150px" src="/static/placeholder.svg" alt="">
        <div class="menu-card-body">
          <div class="menu-card-name">Latte Art Masterclass</div>
          <div class="menu-card-desc">Learn to pour hearts, rosettas, and tulips like a pro.</div>
          <div class="menu-card-desc">2026-08-04 at 16:00 &middot; Rs.599</div>
          <div class="menu-card-footer">
            <span class="menu-card-price">10 seats left</span>
            <button class="menu-card-add">+</button>
          </div>
        </div>
      </div>`,
  },
  {
    name: 'stat-card',
    page: 'customer-dashboard.html',
    selector: '.stat',
    containerOpen: '<div class="container"><div class="stats">',
    containerClose: '</div></div>',
    html: `<div class="stat coins"><h4>Coins</h4><span>128</span></div>`,
  },
  {
    name: 'badge-card',
    page: 'customer-dashboard.html',
    selector: '.bone-badge',
    containerOpen: '<div class="container"><div id="badgesGrid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:12px">',
    containerClose: '</div></div>',
    html: `
      <div class="bone-badge" style="text-align:center;padding:16px 10px;border-radius:12px;border:1px solid var(--border);background:rgba(196,112,75,.08)">
        ${icon(30)}
        <div style="font-family:var(--font-h);font-weight:600;font-size:.85rem;margin-top:6px">First Order</div>
        <div style="font-size:.7rem;color:var(--text-muted)">Unlocked</div>
      </div>`,
  },
  {
    name: 'order-card',
    page: 'customer-dashboard.html',
    selector: '.order',
    containerOpen: '<div class="container"><div id="orders">',
    containerClose: '</div></div>',
    html: `
      <div class="order" data-oid="10">
        <div class="order-head"><h3>Order #10</h3><div style="display:flex;align-items:center;gap:10px"><span class="ostatus badge badge-pending">Pending</span><span style="font-size:.8rem;color:var(--text-muted)">16-07-2026 05:02 PM</span></div></div>
        <div class="order-body">
          <div class="tracker">
            <div class="step active"><div class="circle">1</div><span>Pending</span></div>
            <div class="step"><div class="circle">2</div><span>Preparing</span></div>
            <div class="step"><div class="circle">3</div><span>Ready</span></div>
            <div class="step"><div class="circle">4</div><span>Completed</span></div>
          </div>
          <p style="font-size:.875rem;color:var(--text-muted)"><strong>Items:</strong> Cold Brew Coffee (x1), Edamame Hummus Platter (x1)<br><strong>Total Paid:</strong> &#8377;740</p>
        </div>
      </div>`,
  },
  {
    name: 'admin-order-card',
    page: 'admin-dashboard.html',
    selector: '.order',
    containerOpen: '<div class="container"><div class="section active" id="orders-sec">',
    containerClose: '</div></div>',
    html: `
      <div class="order">
        <div class="order-head"><strong>#10 &middot; Abhi<span class="ch-tag">Dine-in &middot; T3</span></strong><span class="badge badge-pending">Pending</span></div>
        <div class="order-body">
          <div style="display:flex;align-items:center;justify-content:space-between;margin:16px 0 24px;position:relative">
            <div style="position:absolute;top:14px;left:30px;right:30px;height:2px;background:var(--border);z-index:0"></div>
            <div style="display:flex;flex-direction:column;align-items:center;flex:1;position:relative;z-index:1"><div style="width:28px;height:28px;border-radius:50%;background:var(--terracotta);color:#fff;display:flex;align-items:center;justify-content:center;font-size:.75rem;font-weight:700;margin-bottom:6px">1</div><span style="font-size:.65rem;color:var(--espresso);text-transform:uppercase;font-weight:600">Pending</span></div>
            <div style="display:flex;flex-direction:column;align-items:center;flex:1;position:relative;z-index:1"><div style="width:28px;height:28px;border-radius:50%;background:var(--border);color:var(--text-muted);display:flex;align-items:center;justify-content:center;font-size:.75rem;font-weight:700;margin-bottom:6px">2</div><span style="font-size:.65rem;color:var(--text-muted);text-transform:uppercase;font-weight:600">Preparing</span></div>
            <div style="display:flex;flex-direction:column;align-items:center;flex:1;position:relative;z-index:1"><div style="width:28px;height:28px;border-radius:50%;background:var(--border);color:var(--text-muted);display:flex;align-items:center;justify-content:center;font-size:.75rem;font-weight:700;margin-bottom:6px">3</div><span style="font-size:.65rem;color:var(--text-muted);text-transform:uppercase;font-weight:600">Ready</span></div>
            <div style="display:flex;flex-direction:column;align-items:center;flex:1;position:relative;z-index:1"><div style="width:28px;height:28px;border-radius:50%;background:var(--border);color:var(--text-muted);display:flex;align-items:center;justify-content:center;font-size:.75rem;font-weight:700;margin-bottom:6px">4</div><span style="font-size:.65rem;color:var(--text-muted);text-transform:uppercase;font-weight:600">Completed</span></div>
          </div>
          <p><strong>Items:</strong> Cold Brew, Cheesy Garlic Bread</p>
          <p style="margin-top:8px"><strong>Total:</strong> &#8377;382</p>
          <p style="margin-top:8px"><strong>Payment:</strong> Cash</p>
          <button class="btn">Start Preparing</button>
          <button class="btn" style="background:#2c9f4a;margin-left:8px">Mark Paid</button>
          <button class="btn" style="background:#6c5ce7;margin-left:8px">Add Items</button>
          <button class="btn" style="background:#dc3545;margin-left:8px">Cancel</button>
        </div>
      </div>`,
  },
  {
    name: 'admin-menu-item',
    page: 'admin-dashboard.html',
    selector: '.order',
    containerOpen: '<div class="container"><div id="menuItemsList">',
    containerClose: '</div></div>',
    html: `
      <div class="order">
        <div class="order-head">
          <strong>Café Latte — ₹179</strong>
          <span>Hot Coffee</span>
        </div>
        <div class="order-body">
          <div style="display:flex;gap:12px;align-items:center;margin-bottom:8px">
            <img src="/static/placeholder.svg" style="width:56px;height:56px;object-fit:cover;border-radius:8px">
            <p style="flex:1;color:var(--text-muted);font-size:.85rem">Espresso with silky steamed milk.</p>
          </div>
          <button class="btn">Edit</button>
          <button class="btn" style="background:#dc3545;margin-left:8px">Delete</button>
        </div>
      </div>`,
  },
  {
    // Generic simple admin card (header + a couple of lines + two buttons, no
    // progress tracker) — matches the Offers / Tables / Events list cards.
    name: 'admin-list-card',
    page: 'admin-dashboard.html',
    selector: '.order',
    containerOpen: '<div class="container"><div id="offersList">',
    containerClose: '</div></div>',
    html: `
      <div class="order">
        <div class="order-head"><strong>Breakfast Combo</strong><span class="badge badge-ready">Active</span></div>
        <div class="order-body">
          <p style="color:var(--text-muted);font-size:.85rem">A short description of this item goes here.</p>
          <p style="margin-top:6px"><strong>combo</strong> · ₹299</p>
          <button class="btn">Edit</button>
          <button class="btn" style="background:#dc3545;margin-left:8px">Delete</button>
        </div>
      </div>`,
  },
  {
    // POS menu tile (New Order tab) — small card with a name line + price line.
    name: 'pos-item',
    page: 'admin-dashboard.html',
    selector: '.pos-item',
    containerOpen: '<div class="container"><div class="pos-items" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px">',
    containerClose: '</div></div>',
    html: `
      <div class="pos-item">
        <div class="n">Café Latte</div>
        <div class="p">₹179</div>
      </div>`,
  },
  {
    // Gallery photo tile — image block + a caption line.
    name: 'gallery-photo',
    page: 'admin-dashboard.html',
    selector: '.gallery-photo',
    containerOpen: '<div class="container"><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:12px">',
    containerClose: '</div></div>',
    html: `
      <div class="gallery-photo" style="position:relative">
        <img src="/static/placeholder.svg" style="width:100%;height:120px;object-fit:cover;border-radius:8px">
        <p style="font-size:.75rem;color:var(--text-muted);margin-top:4px">Caption text</p>
      </div>`,
  },
  {
    // Analytics summary tile (an-stat) — small label + big value.
    name: 'an-stat',
    page: 'admin-dashboard.html',
    selector: '.an-stat',
    containerOpen: '<div class="container"><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px">',
    containerClose: '</div></div>',
    html: `
      <div class="an-stat">
        <div class="an-stat-label">Revenue</div>
        <div class="an-stat-val">₹12,340</div>
      </div>`,
  },
];
