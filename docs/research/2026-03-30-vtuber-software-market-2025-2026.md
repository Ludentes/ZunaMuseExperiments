# VTuber Software Market Research (2025-2026)

Research date: 2026-03-30. Data sourced from SteamCharts, Warudo docs, GitHub, web searches.

---

## 1. Steam Concurrent User Data (SteamCharts, live as of 2026-03-30)

### VTube Studio (Live2D) — App 1325860
- **Current players**: 7,308
- **24h peak**: 17,774
- **All-time peak**: 23,511
- **Last 30 days avg**: 10,633 (+1.83%)
- **Trend**: Steady growth. Avg went from ~8,500 (mid-2024) to ~10,600 (Mar 2026). ~25% YoY growth.

Monthly averages (most recent first):
| Period | Avg Players | Peak |
|--------|------------|------|
| Mar 2026 (30d) | 10,633 | 19,800 |
| Feb 2026 | 10,442 | 20,077 |
| Jan 2026 | 10,936 | 20,212 |
| Dec 2025 | 10,596 | 23,511 |
| Nov 2025 | 10,526 | 19,325 |
| Oct 2025 | 10,208 | 21,048 |
| Sep 2025 | 10,060 | 19,766 |
| Aug 2025 | 10,522 | 20,693 |
| Jul 2025 | 10,477 | 19,996 |
| Jun 2025 | 10,202 | 19,543 |
| May 2025 | 10,545 | 20,928 |
| Apr 2025 | 10,047 | 20,481 |
| Mar 2025 | 9,621 | 20,014 |
| Feb 2025 | 9,891 | 21,392 |
| Jan 2025 | 9,322 | 18,605 |
| Dec 2024 | 8,959 | 19,977 |
| Nov 2024 | 8,556 | 16,650 |
| Oct 2024 | 8,333 | 16,874 |
| Sep 2024 | 8,377 | 16,443 |
| Aug 2024 | 8,517 | — |

### Warudo (3D VRM) — App 2079120
- **Current players**: 634
- **24h peak**: 1,382
- **All-time peak**: 1,609
- **Last 30 days avg**: 860 (+6.64%)
- **Trend**: Consistent month-over-month growth since launch. Every single month shows gains. Doubled in ~8 months (434 Aug 2025 -> 860 Mar 2026). Quadrupled in ~14 months (264 Jan 2025 -> 860 Mar 2026).

Monthly averages (most recent first):
| Period | Avg Players | Peak |
|--------|------------|------|
| Mar 2026 (30d) | 860 | 1,538 |
| Feb 2026 | 806 | 1,410 |
| Jan 2026 | 795 | 1,399 |
| Dec 2025 | 762 | 1,609 |
| Nov 2025 | 723 | 1,294 |
| Oct 2025 | 696 | 1,269 |
| Sep 2025 | 656 | 1,178 |
| Aug 2025 | 625 | 1,140 |
| Jul 2025 | 601 | 1,104 |
| Jun 2025 | 565 | 1,019 |
| May 2025 | 531 | 945 |
| Apr 2025 | 475 | 880 |
| Mar 2025 | 435 | 810 |
| Feb 2025 | 406 | 736 |
| Jan 2025 | 379 | 670 |
| Dec 2024 | 349 | 683 |
| Nov 2024 | 319 | 533 |
| Oct 2024 | 309 | 545 |
| Sep 2024 | 288 | 517 |
| Aug 2024 | 264 | — |

### Animaze (2D/3D, FaceRig successor) — App 1364390
- **Current players**: 191
- **24h peak**: 356
- **All-time peak**: 1,055
- **Last 30 days avg**: 262 (-10.8 from prior month)
- **Trend**: Declining. Was ~367 in Nov 2025, now ~262. Down from peak avg of ~400+ in late 2024. Dying product.

### Not on Steam (no concurrent data available)
- **VSeeFace** — standalone download, not on Steam
- **VNyan** — itch.io only (SteamCharts returned 500 error)
- **VMagicMirror** — standalone download, not on Steam

### Summary Table (Mar 2026)

| Software | Avg Players | Trend | Category |
|----------|------------|-------|----------|
| VTube Studio | 10,633 | Growing (+25% YoY) | 2D (Live2D) |
| Warudo | 860 | Fast growth (+225% YoY) | 3D (VRM) |
| Animaze | 262 | Declining (-30% from peak) | 2D/3D |

VTube Studio is **12x** the size of Warudo. But Warudo is the fastest-growing VTuber app on Steam.

---

## 2. Warudo Deep Dive

### Pricing Model
- **Steam version: FREE** for personal use (indie streamers included)
- Free for non-streaming activities (testing models, social media content)
- Free for streaming IF you exclusively own your VTuber IP and have no contracted streaming hours (except Twitch/YouTube partner contracts)
- **Warudo Pro**: Paid, pricing unlisted (contact info@warudo.app). Case-by-case pricing.
  - Special "indie pricing" tier available
  - Pro adds: Universal RP (URP), NiloToon rendering, Autodesk MotionBuilder, optical mocap (Vicon, OptiTrack)
- **Bottom line**: Effectively free for all indie VTubers. Pro is for corporate/agency use.

### Platform Support
- **Windows only** (64-bit). Uses DirectX.
- No macOS, no Linux native support.
- Runs on Linux via Steam Proton (tested: GE-Proton-10-26). Requires launch options: `PROTON_DISABLE_NVAPI=1 PROTON_USE_WOW64=1 %command%`
- No announced plans for macOS/Linux ports.

### VMC Protocol Support
- **Full VMC receiver support** (port 39539 default)
- Accepts VMC data from: VirtualMotionCapture, VSeeFace, any VMC-compatible app
- Also has a **VMC Sender** asset (can output VMC data)
- Supports: face tracking (MediaPipe/OpenSeeFace/ARKit), hand tracking (LeapMotion, webcam), full body (VMC, Mocopi, VR trackers)
- Limitation: All bone rotations must be zero in T-pose (standard VRM requirement)

### Key Features vs VSeeFace
| Feature | Warudo | VSeeFace |
|---------|--------|----------|
| Price | Free (Steam) | Free |
| Mouth tracking | Audio + mocap simultaneously | Audio OR mocap (not both) |
| Hand tracking | Built-in (webcam/iPhone) | Leap Motion only |
| VMC input | Yes | Yes |
| VMC output | Yes (VMC Sender) | Yes |
| Visual scripting | Node-based blueprints | No |
| Idle animations | 500+ built-in | No |
| Mod SDK | Yes (Unity-based) | No |
| Stream Deck | Yes | No |
| Platform | Windows only | Windows only |
| VRM support | VRM 0/1 + WarudoMod | VRM + VSFAvatar |

### Steam Reviews
- 93% positive (558 reviews)
- Last 30 days: 100% positive (25 reviews)

### Development Status
- Active development by Hakuya Labs
- As of April 2025: "feature-complete 3D VTubing solution"
- Working on bug fixes and UX improvements before 1.0 launch
- Latest update: 0.12.16

---

## 3. The 3D VRM VTuber Market

### Market Share: 2D vs 3D
- **2D (Live2D) dominates**: 52-59% market share in 2025 (sources vary)
- **3D avatars**: ~32% of creator base, growing at 11.17% CAGR
- Strategic coexistence: indie creators use 2D for daily streams, test 3D for music videos/collabs
- Live2D's 2024 physics update narrowed the realism gap
- Open-source Inochi2D reducing Live2D licensing barriers

### What 3D VTubers Use (2025-2026)

**Active, maintained 3D VRM software:**

| Software | Price | Platform | VMC In | VMC Out | Status |
|----------|-------|----------|--------|---------|--------|
| Warudo | Free (Steam) | Windows | Yes | Yes | Active, fast growth |
| VNyan | Free (itch.io) | Windows | Yes | ? | Active |
| VSeeFace | Free | Windows | Yes | Yes | Maintained (sporadic updates) |
| Brioche Puppet | Free (FOSS) | Win/Mac/Linux | Yes | ? | Active, new |
| VMagicMirror | Free | Windows | No | No | Unclear maintenance |
| VTuber Plus | Paid (itch.io) | Windows | ? | ? | Active |
| Live3D | $3.9/mo+ | Web/Windows | No | No | Active |

**Discontinued/declining:**
- Animaze: declining on Steam (262 avg, was 400+)
- VUP: removed from Steam
- VPupPr: archived (2022), community forks exist
- 3tene, Luppet, Hitogata: unclear maintenance

### VSeeFace Status
- **NOT abandoned** but development is sporadic
- Last release: v1.13.38c4 (February 2025)
- Previous release: v1.13.38b (October 2024)
- Release pattern: clusters of patches then months of silence
- Still widely used but community increasingly moving to Warudo/VNyan
- Key limitation: cannot do audio + motion mouth tracking simultaneously

### What's Replacing VSeeFace?
1. **Warudo** — fastest growing, most feature-rich, free
2. **VNyan** — strong in customization (node-based), Twitch integration
3. Warudo's main advantage: mouth tracking (audio+mocap), hand tracking, 500+ animations, visual scripting
4. Barrier to switching: VSeeFace's .vsfavatar format not compatible with Warudo (Unity version mismatch)

---

## 4. Linux VTuber Usage

### Community Size
- **Tiny niche.** No hard numbers found anywhere.
- The "Awesome VTubing on Linux" GitHub repo has **7 stars, 1 fork** (created Sep 2025)
- Multiple guides exist (Codeberg, GitHub gists) suggesting active but very small community
- A FOSS United talk "How to start Vtubing on Linux" was submitted for MiniDebConf 2025

### What Linux VTubers Use

**Native Linux options:**
| Software | Type | Status | Notes |
|----------|------|--------|-------|
| SnekStudio | 3D VRM | Active | FOSS, Flatpak, MediaPipe |
| Brioche Puppet | 3D VRM/MMD | Active | FOSS, Steam, MediaPipe |
| OpenVT | 2D Live2D | New | FOSS, Godot-based |
| XR Animator | 3D | Active | Electron, face+body+hand |
| Kalidoface 3D | 3D VRM | Active | Web-based, MediaPipe |
| OpenSeeFace | Tracking only | Active | Python, feeds other apps |

**Via Proton (not native):**
| Software | Proton Status | Notes |
|----------|--------------|-------|
| VTube Studio | Works | Steam Proton |
| Warudo | Works | Needs GE-Proton + launch flags |
| VSeeFace | Works | Via Lutris/Proton |
| VNyan | Works | Proton-compatible |

**Key Linux challenges:**
- Virtual camera (v4l2loopback) setup required for OBS integration
- Transparency/compositing issues on X11
- Some webcam tracking behaves differently
- BlendShape naming incompatibilities between VRoid Studio (Proton) and Warudo

### Is This a Real Market?
No. The Linux VTuber community is a hobbyist niche within a niche. Evidence:
- 7 GitHub stars on the main resource list
- Guides written by individuals, not organizations
- No commercial VTuber software targets Linux natively
- Even the dedicated blog post ("Cold Start VTubing in Linux for 2026") is by a single hobbyist
- Most Linux VTubers just run Windows software through Proton

---

## 5. Key Takeaways for Muse-VTuber Project

1. **VTube Studio dominates** (10K+ concurrent) but is 2D-only (Live2D). Not relevant for our VMC/VRM output.
2. **Warudo is THE target** for 3D VRM VTubers. 860 avg users, fastest growth, free, supports VMC input natively on port 39539.
3. **VNyan is secondary target** — popular but not on Steam so harder to measure. Supports VMC input.
4. **VSeeFace still works** but is stagnating. Users are migrating to Warudo.
5. **Linux native is not worth targeting** — the community is too small. Proton compatibility covers the need.
6. **The 3D VRM market is growing** (11% CAGR) but still smaller than Live2D (~60/40 split favoring 2D).
7. **VMC protocol is the right integration choice** — accepted by Warudo, VSeeFace, VNyan, Brioche Puppet.

---

## Sources

- SteamCharts VTube Studio: https://steamcharts.com/app/1325860
- SteamCharts Warudo: https://steamcharts.com/app/2079120
- SteamCharts Animaze: https://steamcharts.com/app/1364390
- Warudo Handbook: https://docs.warudo.app/docs
- Warudo Pro pricing: https://docs.warudo.app/docs/pro
- Warudo VMC docs: https://docs.warudo.app/docs/mocap/vmc
- VSeeFace releases: https://github.com/emilianavt/VSeeFaceReleases/releases
- Best VTuber Software (emilianavt gist): https://gist.github.com/emilianavt/cbf4d6de6f7fb01a42d4cce922795794
- Awesome VTubing on Linux: https://github.com/VTubing-on-Linux/Awesome-VTubing-on-Linux
- Cold Start VTubing in Linux: https://letsbuildroboticswithshadow8472.com/index.php/2025/12/29/cold-start-vtubing-in-linux-for-2026/
- Linux Guide to Vtubing: https://codeberg.org/KyloNeko/Linux-Guide-to-Vtubing
- Mordor Intelligence VTuber Market: https://www.mordorintelligence.com/industry-reports/vtuber-market
- SkyQuest VTuber Market: https://www.skyquestt.com/report/vtuber-market
- Warudo Steam page: https://store.steampowered.com/app/2079120/Warudo/
- Brioche Puppet Steam: https://store.steampowered.com/app/4286130/Brioche_Puppet/
- VMC compatibility tweet (Brielle Garcia): https://x.com/tacolamp/status/1825387999242367231
