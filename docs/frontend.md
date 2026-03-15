# Frontend Architecture

The frontend is a Next.js 14 application with TypeScript, Tailwind CSS, and a component library built with CVA (class-variance-authority).

## Tech Stack

| Library | Version | Purpose |
|---------|---------|---------|
| Next.js | 14.2.29 | React framework with App Router |
| React | 18.3.1 | UI library |
| TypeScript | 5.8.3 | Type safety |
| Tailwind CSS | 3.4.17 | Utility-first styling |
| SWR | 2.3.3 | Data fetching with caching + revalidation |
| Zustand | 5.0.5 | Lightweight state management |
| Recharts | 2.15.3 | Charts and visualizations |
| Lucide React | 0.513.0 | Icon library |
| CVA | 0.7.1 | Component variant abstraction |
| clsx + tailwind-merge | — | Conditional class merging |

## Project Structure

```
frontend/src/
├── app/                    # Next.js App Router pages
│   ├── layout.tsx          # Root layout with sidebar
│   ├── page.tsx            # Dashboard
│   ├── globals.css         # Tailwind + CSS variables
│   ├── orders/page.tsx     # Orders page
│   ├── portfolio/page.tsx  # Portfolio page
│   ├── strategies/page.tsx # Strategies page
│   ├── mock/page.tsx       # Mock testing page
│   ├── providers/page.tsx  # Providers page
│   └── settings/page.tsx   # Settings page
├── components/             # Reusable components
│   ├── ui/                 # Base UI primitives
│   ├── dashboard/          # Dashboard-specific components
│   ├── mock/               # Mock testing components
│   ├── strategies/         # Strategy components
│   └── providers/          # Provider components
├── hooks/                  # Custom React hooks
│   ├── useData.ts          # SWR data fetching hooks
│   └── useTickStream.ts    # WebSocket tick hook
├── lib/                    # Utilities and API client
│   ├── api.ts              # Full REST API client
│   └── utils.ts            # Formatting utilities
├── types/                  # TypeScript interfaces
│   └── index.ts            # All type definitions
└── __tests__/              # Jest test suite
    ├── utils.test.ts
    ├── api.test.ts
    ├── components.test.tsx
    └── hooks.test.ts
```

## Pages

### Dashboard (`/`)
Main overview with four metric cards (Daily P&L, Open Positions, Active Strategies, Kill Switch status), open positions panel, recent orders panel, and risk monitoring panel.

### Orders (`/orders`)
Order management with:
- Place Order form (exchange, symbol, type, quantity, price, product)
- Orders table with real-time status badges (COMPLETE → green, REJECTED → red, OPEN → blue)
- Cancel action for pending orders

### Portfolio (`/portfolio`)
Three sections:
- **Margins Overview**: Available balance, used margin, net margin
- **Positions Table**: Net and day positions with real-time P&L
- **Holdings Table**: Long-term equity holdings

### Strategies (`/strategies`)
Strategy control panel:
- Strategy cards with metrics grid (signals, trades, win rate, P&L)
- Start/Stop/Pause/Resume controls
- Parameter editing
- State badges (running → green, paused → yellow, etc.)

### Mock Testing (`/mock`)
Paper trading workspace:
- Create session form (capital, dates)
- Session overview (capital, P&L, time, progress)
- Time controls (market open/close, next day, speed, pause/resume, date picker, reset)
- Mock positions and orders tables

### Providers (`/providers`)
Provider management:
- Provider cards with activation and health check
- Active provider indicator
- Connection status

### Settings (`/settings`)
Risk configuration:
- Kill switch panel with activate/deactivate
- Risk limits form (all configurable values)

## Component Library

### UI Components (`src/components/ui/`)

| Component | Props | Description |
|-----------|-------|-------------|
| `Card` | `className`, `noPadding` | Container with border and background |
| `CardHeader` | `className` | Card header section |
| `CardTitle` | `className` | Card title text |
| `Button` | `variant`, `size`, `disabled` | CVA-based button (primary/danger/outline/ghost, sm/md/lg) |
| `Badge` | `variant` | Status badge (success/danger/warning/info/neutral) |
| `StatusBadge` | `status` | Auto-maps order/strategy status strings to badge variants |
| `Input` | `label`, all HTML input props | Form input with optional label |
| `Select` | `label`, `options`, all HTML select props | Form select with options |
| `Table` | `className` | Table container |
| `TableHeader` | — | Table header wrapper |
| `TableBody` | — | Table body wrapper |
| `TableRow` | — | Table row |
| `TableHead` | — | Column header cell |
| `TableCell` | — | Data cell |
| `EmptyRow` | `colSpan`, `message` | Empty state row |
| `LoadingRow` | `colSpan` | Loading state row |
| `MetricCard` | `title`, `value`, `subtitle` | Dashboard metric display |
| `ProgressBar` | `value`, `max`, `label` | Horizontal progress bar with auto-coloring |
| `PageHeader` | `title`, `subtitle`, `action` | Consistent page header |
| `EmptyState` | `icon`, `title`, `description`, `action` | Placeholder for empty content |
| `Sidebar` | — | Navigation sidebar with active state |

### Domain Components

| Component | Directory | Description |
|-----------|-----------|-------------|
| `PlaceOrderForm` | `dashboard/` | Order placement form |
| `RiskPanel` | `dashboard/` | Risk monitoring panel |
| `CreateSessionForm` | `mock/` | Mock session creation |
| `TimeControls` | `mock/` | Time manipulation panel |
| `StrategyCard` | `strategies/` | Strategy display with controls |
| `ProviderCard` | `providers/` | Provider card with activate/health |

## Data Fetching

### SWR Hooks (`useData.ts`)

All data hooks use SWR for automatic caching, revalidation, and polling:

| Hook | Endpoint | Refresh |
|------|----------|---------|
| `useOrders()` | `/orders/` | 3s |
| `usePositions()` | `/portfolio/positions` | 3s |
| `useHoldings()` | `/portfolio/holdings` | 10s |
| `useMargins()` | `/portfolio/margins` | 5s |
| `useStrategies()` | `/strategies/` | 2s |
| `useRiskStatus()` | `/config/risk/status` | 2s |
| `useRiskLimits()` | `/config/risk/limits` | one-time |
| `useProviders()` | `/providers/` | one-time |
| `useMockStatus()` | `/mock/session` | 1s |

### WebSocket Hook (`useTickStream.ts`)

Connects to `ws://localhost:8000/ws/ticks/{clientId}` for real-time tick data:

```typescript
const { connected, subscribe, unsubscribe } = useTickStream({
  clientId: "dashboard",
  tokens: [256265, 341249],
  onTick: (tick) => updatePrice(tick),
  enabled: true,
});
```

## API Client (`lib/api.ts`)

The API client wraps `fetch` with:
- Automatic `Content-Type: application/json` headers
- Error handling → throws `ApiError` with status code
- Organized into namespaces: `auth`, `orders`, `portfolio`, `market`, `strategies`, `providers`, `config`, `mock`, `health`

API URLs are proxied through Next.js rewrites:
```
Frontend fetch("/api/orders/") → Next.js proxy → Backend http://localhost:8000/api/orders/
```

## Utilities (`lib/utils.ts`)

| Function | Description |
|----------|-------------|
| `cn(...classes)` | Merge Tailwind classes (clsx + tailwind-merge) |
| `formatCurrency(value)` | Format as INR (₹1,234.56) |
| `formatPnl(value)` | P&L with sign prefix (+₹1,234 / -₹567) |
| `formatNumber(value, decimals)` | Generic number formatting |
| `formatPercent(value)` | Percentage with sign (+1.23% / -0.45%) |

## Styling

### CSS Variables (`globals.css`)

```css
--background: #0a0a0a    /* Dark background */
--foreground: #ededed     /* Light text */
--card: #141414           /* Card background */
--card-border: #262626    /* Card border */
--muted: #737373          /* Muted text */
--accent: #3b82f6         /* Blue accent */
--success: #10b981        /* Green */
--danger: #ef4444         /* Red */
--warning: #f59e0b        /* Amber */
```

### Design System
- Dark theme throughout
- Cards with subtle borders
- Status-colored badges
- P&L color coding (green positive, red negative)
- Fonts: JetBrains Mono (monospace) + Outfit (sans-serif)

## API Proxy

Next.js rewrites in `next.config.mjs`:
```js
async rewrites() {
  return [
    {
      source: "/api/:path*",
      destination: "http://localhost:8000/api/:path*",
    },
  ];
}
```

This avoids CORS issues and keeps the frontend agnostic of the backend URL.
