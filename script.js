function eventDate(dayOffset, time) {
  const [hours, minutes] = time.split(":").map(Number);
  const date = new Date();
  date.setDate(date.getDate() + dayOffset);
  date.setHours(hours, minutes, 0, 0);
  return date.toISOString();
}

const demoEvents = [
  {
    id: "meetfactory-sound",
    title: "Indie Sound Night at MeetFactory",
    category: "Music",
    district: "Smichov",
    venue: "MeetFactory",
    date: eventDate(1, "20:00"),
    price: 390,
    popularity: 91,
    english: true,
    color: "#7246a8",
    tags: ["Live", "After work", "Indoor"],
    description: "A compact club night with Prague-based indie bands, guest DJs, and a late bar near Smichov station."
  },
  {
    id: "naplavka-market",
    title: "Naplavka Riverside Farmers Market",
    category: "Food",
    district: "Vysehrad",
    venue: "Naplavka",
    date: eventDate(6, "09:00"),
    price: 0,
    popularity: 88,
    english: true,
    color: "#33794c",
    tags: ["Open air", "Family", "Morning"],
    description: "Seasonal produce, bakery stalls, coffee, street food, and a slow riverside Saturday by the Vltava."
  },
  {
    id: "dox-design-talk",
    title: "Design Futures Talk",
    category: "Talks",
    district: "Holesovice",
    venue: "DOX Centre",
    date: eventDate(2, "18:30"),
    price: 180,
    popularity: 74,
    english: true,
    color: "#007f7a",
    tags: ["Design", "English", "Evening"],
    description: "A panel on urban design, creative tooling, and how Prague's cultural spaces are adapting for new audiences."
  },
  {
    id: "vinohrady-wine",
    title: "Vinohrady Natural Wine Walk",
    category: "Food",
    district: "Vinohrady",
    venue: "Jiriho z Podebrad",
    date: eventDate(5, "17:30"),
    price: 650,
    popularity: 82,
    english: true,
    color: "#9e3f4f",
    tags: ["Tasting", "Small group", "Outdoor"],
    description: "A guided route through neighborhood bars and bottle shops with Czech and Central European natural wines."
  },
  {
    id: "kasarna-cinema",
    title: "Courtyard Cinema: Czech New Wave",
    category: "Film",
    district: "Karlin",
    venue: "Kasarna Karlin",
    date: eventDate(4, "21:00"),
    price: 120,
    popularity: 79,
    english: false,
    color: "#c8941d",
    tags: ["Cinema", "Courtyard", "Subtitles"],
    description: "An outdoor screening in a relaxed courtyard with drinks, simple food, and a crowd that actually watches the film."
  },
  {
    id: "letna-yoga",
    title: "Sunset Yoga in Letna Park",
    category: "Wellness",
    district: "Letna",
    venue: "Letna Park",
    date: eventDate(0, "19:00"),
    price: 250,
    popularity: 63,
    english: true,
    color: "#4b7b8a",
    tags: ["Outdoor", "Beginner", "Sunset"],
    description: "A calm open-level session overlooking the city, followed by an optional tea stop nearby."
  },
  {
    id: "zizkov-gallery",
    title: "Zizkov Open Studios",
    category: "Art",
    district: "Zizkov",
    venue: "Multiple venues",
    date: eventDate(6, "14:00"),
    price: 0,
    popularity: 86,
    english: false,
    color: "#d63f2e",
    tags: ["Gallery", "Free", "Walkable"],
    description: "Independent artists open their studios for one afternoon with prints, installations, and informal conversations."
  },
  {
    id: "cross-electronic",
    title: "Electronic Garden Session",
    category: "Nightlife",
    district: "Holesovice",
    venue: "Cross Club",
    date: eventDate(6, "22:00"),
    price: 320,
    popularity: 94,
    english: true,
    color: "#4f5f25",
    tags: ["Late", "DJ", "Dance"],
    description: "A multi-floor electronic night with an outdoor garden opener and a heavier room after midnight."
  },
  {
    id: "manifesto-brunch",
    title: "Manifesto Weekend Brunch",
    category: "Food",
    district: "Andel",
    venue: "Manifesto Market",
    date: eventDate(7, "11:00"),
    price: 450,
    popularity: 70,
    english: true,
    color: "#b85f32",
    tags: ["Brunch", "Market", "Group"],
    description: "Rotating kitchens, coffee, cocktails, and easy covered seating for a low-friction weekend meetup."
  },
  {
    id: "rudolfinum-chamber",
    title: "Chamber Evening at Rudolfinum",
    category: "Classical",
    district: "Old Town",
    venue: "Rudolfinum",
    date: eventDate(1, "19:30"),
    price: 790,
    popularity: 77,
    english: true,
    color: "#344b77",
    tags: ["Seated", "Historic", "Dressy"],
    description: "A concise chamber program in one of Prague's most handsome concert halls, ideal for a quieter evening."
  }
];

demoEvents.forEach(event => {
  event.source = event.source || "Demo";
  event.sourceUrl = event.sourceUrl || "https://prague.eu/en/akce-kategorie/events/";
});

const events = Array.isArray(window.EVENTS) && window.EVENTS.length ? window.EVENTS : demoEvents;

const state = {
  query: "",
  date: "all",
  category: "all",
  district: "all",
  maxPrice: 1500,
  freeOnly: false,
  englishFriendly: false,
  sort: "soon",
  selectedId: events[0].id,
  saved: new Set(JSON.parse(localStorage.getItem("savedEvents") || "[]")),
  savedOnly: false
};

const els = {
  searchForm: document.querySelector("#searchForm"),
  searchInput: document.querySelector("#searchInput"),
  categorySelect: document.querySelector("#categorySelect"),
  districtSelect: document.querySelector("#districtSelect"),
  priceRange: document.querySelector("#priceRange"),
  priceLabel: document.querySelector("#priceLabel"),
  freeOnly: document.querySelector("#freeOnly"),
  englishFriendly: document.querySelector("#englishFriendly"),
  sortSelect: document.querySelector("#sortSelect"),
  eventList: document.querySelector("#eventList"),
  resultSummary: document.querySelector("#resultSummary"),
  detailPanel: document.querySelector("#detailPanel"),
  savedCount: document.querySelector("#savedCount"),
  savedToggle: document.querySelector("#savedToggle"),
  resetFilters: document.querySelector("#resetFilters"),
  themeToggle: document.querySelector("#themeToggle")
};

const formatDate = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short"
});

const formatTime = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit"
});

function priceText(price) {
  if (price === null || price === undefined) return "Listed";
  return price ? `${price} Kc` : "Free";
}

function init() {
  fillSelect(els.categorySelect, [...new Set(events.map(event => event.category))]);
  fillSelect(els.districtSelect, [...new Set(events.map(event => event.district))]);
  bindEvents();
  updatePriceLabel();
  render();
  renderIcons();
}

function fillSelect(select, values) {
  values.sort().forEach(value => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  });
}

function bindEvents() {
  els.searchForm.addEventListener("submit", event => {
    event.preventDefault();
    state.query = els.searchInput.value.trim().toLowerCase();
    render();
  });

  els.searchInput.addEventListener("input", event => {
    state.query = event.target.value.trim().toLowerCase();
    render();
  });

  document.querySelector("#dateFilters").addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button) return;
    document.querySelectorAll("[data-filter='date']").forEach(item => item.classList.remove("active"));
    button.classList.add("active");
    state.date = button.dataset.value;
    render();
  });

  els.categorySelect.addEventListener("change", event => {
    state.category = event.target.value;
    render();
  });

  els.districtSelect.addEventListener("change", event => {
    state.district = event.target.value;
    render();
  });

  els.priceRange.addEventListener("input", event => {
    state.maxPrice = Number(event.target.value);
    updatePriceLabel();
    render();
  });

  els.freeOnly.addEventListener("change", event => {
    state.freeOnly = event.target.checked;
    render();
  });

  els.englishFriendly.addEventListener("change", event => {
    state.englishFriendly = event.target.checked;
    render();
  });

  els.sortSelect.addEventListener("change", event => {
    state.sort = event.target.value;
    render();
  });

  els.savedToggle.addEventListener("click", () => {
    state.savedOnly = !state.savedOnly;
    els.savedToggle.classList.toggle("active", state.savedOnly);
    render();
  });

  els.resetFilters.addEventListener("click", resetFilters);

  els.themeToggle.addEventListener("click", () => {
    const isDark = document.documentElement.dataset.theme === "dark";
    document.documentElement.dataset.theme = isDark ? "" : "dark";
    els.themeToggle.innerHTML = `<i data-lucide="${isDark ? "moon" : "sun"}"></i>`;
    renderIcons();
  });
}

function resetFilters() {
  state.query = "";
  state.date = "all";
  state.category = "all";
  state.district = "all";
  state.maxPrice = 1500;
  state.freeOnly = false;
  state.englishFriendly = false;
  state.savedOnly = false;
  els.searchInput.value = "";
  els.categorySelect.value = "all";
  els.districtSelect.value = "all";
  els.priceRange.value = "1500";
  els.freeOnly.checked = false;
  els.englishFriendly.checked = false;
  els.savedToggle.classList.remove("active");
  document.querySelectorAll("[data-filter='date']").forEach(button => {
    button.classList.toggle("active", button.dataset.value === "all");
  });
  updatePriceLabel();
  render();
}

function updatePriceLabel() {
  els.priceLabel.textContent = state.maxPrice >= 1500 ? "Any" : `${state.maxPrice} Kc`;
}

function render() {
  const filtered = filteredEvents();
  if (!filtered.some(event => event.id === state.selectedId)) {
    state.selectedId = filtered[0]?.id || events[0].id;
  }
  renderList(filtered);
  renderDetail(events.find(event => event.id === state.selectedId));
  els.resultSummary.textContent = `${filtered.length} ${filtered.length === 1 ? "match" : "matches"}`;
  els.savedCount.textContent = state.saved.size;
  renderIcons();
}

function filteredEvents() {
  return events
    .filter(event => {
      const haystack = `${event.title} ${event.category} ${event.district} ${event.venue} ${event.tags.join(" ")} ${event.description}`.toLowerCase();
      const eventDate = new Date(event.date);
      const isWeekend = [0, 6].includes(eventDate.getDay());
      const isToday = eventDate.toDateString() === new Date().toDateString();

      return (!state.query || haystack.includes(state.query))
        && (state.date === "all" || (state.date === "today" && isToday) || (state.date === "weekend" && isWeekend))
        && (state.category === "all" || event.category === state.category)
        && (state.district === "all" || event.district === state.district)
        && (event.price === null || event.price === undefined || event.price <= state.maxPrice)
        && (!state.freeOnly || event.price === 0)
        && (!state.englishFriendly || event.english)
        && (!state.savedOnly || state.saved.has(event.id));
    })
    .sort((a, b) => {
      if (state.sort === "price") return (a.price ?? 99999) - (b.price ?? 99999);
      if (state.sort === "popular") return b.popularity - a.popularity;
      return new Date(a.date) - new Date(b.date);
    });
}

function renderList(items) {
  if (!items.length) {
    els.eventList.innerHTML = `<div class="empty-state">No events match those filters.</div>`;
    return;
  }

  els.eventList.innerHTML = items.map(event => {
    const date = new Date(event.date);
    return `
      <div class="event-card ${event.id === state.selectedId ? "active" : ""}">
        <button class="event-select" type="button" data-id="${event.id}" aria-label="Show details for ${event.title}">
          <span class="date-tile">
            <span>${date.toLocaleString("en-GB", { month: "short" })}</span>
            <strong>${date.getDate()}</strong>
          </span>
          <span class="event-body">
            <h3 class="event-title">${event.title}</h3>
            <span class="event-meta">
              <span><i data-lucide="clock"></i>${formatTime.format(date)}</span>
              <span><i data-lucide="map-pin"></i>${event.district}</span>
              <span><i data-lucide="building-2"></i>${event.venue}</span>
            </span>
            <span class="tag-row">
              <span class="tag">${event.category}</span>
              ${event.english ? `<span class="tag">English-friendly</span>` : ""}
              ${event.tags.slice(0, 2).map(tag => `<span class="tag">${tag}</span>`).join("")}
            </span>
          </span>
          <span class="price-pill">${priceText(event.price)}</span>
        </button>
        <a class="card-open" href="${event.sourceUrl}" target="_blank" rel="noopener" aria-label="Open ${event.title} on ${event.source || "source site"}">
          <i data-lucide="external-link"></i>
          <span>Open</span>
        </a>
      </div>
    `;
  }).join("");

  els.eventList.querySelectorAll(".event-select").forEach(button => {
    button.addEventListener("click", () => {
      state.selectedId = button.dataset.id;
      render();
    });
  });
}

function renderDetail(event) {
  const date = new Date(event.date);
  const saved = state.saved.has(event.id);
  els.detailPanel.style.setProperty("--detail-color", event.color);
  els.detailPanel.innerHTML = `
    <div class="detail-media">
      <h3>${event.title}</h3>
      <p>${event.category} in ${event.district}</p>
    </div>
    <div class="detail-content">
      <div class="detail-actions">
        <a class="primary-btn" href="${event.sourceUrl}" target="_blank" rel="noopener">
          <i data-lucide="ticket"></i>
          <span>View event</span>
        </a>
        <button class="save-btn" id="saveSelected" type="button" aria-label="${saved ? "Unsave event" : "Save event"}" title="${saved ? "Unsave event" : "Save event"}">
          <i data-lucide="${saved ? "bookmark-check" : "bookmark"}"></i>
        </button>
      </div>
      <div class="detail-line"><i data-lucide="calendar"></i><strong>${formatDate.format(date)}</strong> at ${formatTime.format(date)}</div>
      <div class="detail-line"><i data-lucide="map-pin"></i><strong>${event.venue}</strong>, ${event.district}</div>
      <div class="detail-line"><i data-lucide="wallet"></i><strong>${priceText(event.price)}</strong></div>
      <div class="detail-line"><i data-lucide="external-link"></i><strong>${event.source || "Source"}</strong></div>
      <p>${event.description}</p>
      <div class="tag-row">
        ${event.tags.map(tag => `<span class="tag">${tag}</span>`).join("")}
        ${event.english ? `<span class="tag">English-friendly</span>` : `<span class="tag">Czech-led</span>`}
      </div>
    </div>
  `;

  document.querySelector("#saveSelected").addEventListener("click", () => toggleSave(event.id));
}

function toggleSave(id) {
  if (state.saved.has(id)) {
    state.saved.delete(id);
  } else {
    state.saved.add(id);
  }
  localStorage.setItem("savedEvents", JSON.stringify([...state.saved]));
  render();
}

function renderIcons() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

if ("serviceWorker" in navigator && location.protocol === "https:") {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js");
  });
}

init();
