# Weekly Progress Agent - Frontend

A modern Next.js dashboard for the Weekly Progress Agent, built with React 18, TypeScript, Tailwind CSS, and shadcn/ui components.

## Features

- 📊 **Dashboard** - Overview of statistics, category breakdown, and recent entries
- 🎤 **Voice Entries** - Browse and search all transcribed voice notes
- 📝 **LinkedIn Posts** - View, edit, copy, and generate weekly posts
- 📅 **Daily Summaries** - Review daily reflections with productivity scores
- ⚙️ **Settings** - Configure timezone, tones, schedules, and nudges
- 🌓 **Dark Mode** - Full dark/light theme support
- 📱 **Responsive** - Mobile-first design with collapsible sidebar

## Tech Stack

- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **Components**: Radix UI primitives (shadcn/ui style)
- **Icons**: Lucide React
- **State**: React hooks (no external state management needed)

## Getting Started

### Prerequisites

- Node.js 18+ 
- npm or yarn or pnpm
- Backend server running on `http://localhost:8000`

### Installation

1. Install dependencies:

```bash
npm install
# or
yarn install
# or
pnpm install
```

2. Create environment file:

```bash
cp .env.example .env.local
```

3. Configure the backend URL in `.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

4. Start the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
```

5. Open [http://localhost:3000](http://localhost:3000) in your browser.

## Project Structure

```
frontend/
├── src/
│   ├── app/                    # Next.js App Router
│   │   ├── globals.css         # Global styles + CSS variables
│   │   ├── layout.tsx          # Root layout with providers
│   │   └── page.tsx            # Main page with view routing
│   ├── components/
│   │   ├── ui/                 # Reusable UI components
│   │   │   ├── button.tsx
│   │   │   ├── card.tsx
│   │   │   ├── dialog.tsx
│   │   │   ├── badge.tsx
│   │   │   ├── input.tsx
│   │   │   ├── select.tsx
│   │   │   ├── tabs.tsx
│   │   │   ├── toast.tsx
│   │   │   └── ...
│   │   ├── layout/             # Layout components
│   │   │   ├── header.tsx
│   │   │   └── sidebar.tsx
│   │   ├── dashboard/          # Dashboard view
│   │   ├── entries/            # Entries view
│   │   ├── posts/              # Posts view
│   │   ├── summaries/          # Summaries view
│   │   ├── settings/           # Settings view
│   │   └── theme-provider.tsx  # Dark mode provider
│   └── lib/
│       └── utils.ts            # Utility functions + API helper
├── package.json
├── tailwind.config.js
├── tsconfig.json
└── next.config.js
```

## API Integration

The frontend communicates with the backend through REST API endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | System health check |
| `/api/stats` | GET | Dashboard statistics |
| `/api/entries` | GET | List voice entries |
| `/api/posts` | GET | List generated posts |
| `/api/posts/:id` | PUT | Update post content |
| `/api/summaries` | GET | List daily summaries |
| `/api/settings` | GET/PUT | User settings |
| `/api/generate-post` | POST | Generate new post |

## Customization

### Theme Colors

Edit the CSS variables in `src/app/globals.css`:

```css
:root {
  --primary: 222.2 47.4% 11.2%;
  --secondary: 210 40% 96.1%;
  /* ... */
}

.dark {
  --primary: 210 40% 98%;
  --secondary: 217.2 32.6% 17.5%;
  /* ... */
}
```

### Adding New Views

1. Create a new component in `src/components/{view-name}/`
2. Add the view type to `ViewType` in `sidebar.tsx`
3. Add navigation item to `navItems` in `sidebar.tsx`
4. Add case to `renderView()` in `page.tsx`

## Build for Production

```bash
npm run build
npm start
```

## Docker

Build and run with Docker:

```bash
docker build -t weekly-agent-frontend .
docker run -p 3000:3000 weekly-agent-frontend
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `NEXT_PUBLIC_API_URL` | Backend API URL | `http://localhost:8000` |

## License

MIT
