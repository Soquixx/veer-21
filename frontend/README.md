# VEER-21 Frontend

React + Vite frontend for VEER-21. The public landing page renders without the API, database, Docker, or the planning engine. Sign-in and operational workspace actions use the real FastAPI API configured for this frontend.

## Visual theme and assets

The frontend uses a light institutional theme inspired by the supplied reference: a warm-white canvas, saffron/white/green accents, serif hero typography, an original VEER·21 roundel, and a subtle aircraft silhouette. Local artwork is bundled in `public/assets/`, so these visuals do not rely on an external image host. The reference is not reproduced as a government seal, and VEER·21 is not presented as an official government website. See `ASSET_SOURCES.md` for the visual asset research and licensing notes.

## Run the frontend locally

Requirements: Node.js 20+ and npm.

```bash
npm install
npm run dev
```

Open the address Vite prints, usually `http://localhost:5173`. Or run `node serve.mjs` for the one-command convenience launcher.

- With no signed-in session, the landing page is the entry route.
- **Open workspace** opens the existing sign-in page.
- The public page is usable while the API is offline. Sign-in and operational actions require a reachable API and a user account created by the backend administrator.
- All scenario data remains server-owned; the frontend does not create substitute results to hide API failures.

## Configure the API

Local default: `http://localhost:8000`.

### Local development

Create `.env` from `.env.example`, then set:

```env
VITE_API_BASE_URL=http://localhost:8000
```

Restart Vite after editing `.env`.

### Static hosting (Vercel, Netlify, or another static host)

Build and publish the **frontend folder only**. No Python runtime or Docker is needed to serve the landing page.

```bash
npm install
npm run build
```

Publish the generated `dist/` directory. Before or after building, configure `public/config.js` with the publicly reachable backend URL:

```js
window.VEER_API_BASE_URL = 'https://YOUR-DEPLOYED-API-DOMAIN';
```

The file is copied to `dist/config.js`, so it can be edited on the deployed static files without rebuilding. Do not use `localhost` or `127.0.0.1` for a remote frontend: in a visitor's browser that points to the visitor's own device, not your computer or backend server. Leave it empty for local development.

The backend must be deployed separately for sign-in and operational functions. Configure its `AIROPS_CORS_ORIGINS` to include the frontend's exact origin (for example, `https://your-site.netlify.app`) and its database/secret variables using the backend deployment instructions. Use HTTPS for both frontend and API. A landing page working without an API does not mean API-backed workspace functions can work without a server.

## Workspace capabilities

- **Overview:** scenario summary, illustrative sector map, assignment coverage, and summary export.
- **Mission board:** searchable and filterable missions and assignment details.
- **Scenario lab:** simulated events, impact analysis, alternative-plan jobs, and approval/rejection workflows.
- **Readiness & feeds:** provenance, freshness, and conflict details from the API.
- **Decision history:** saved scenario versions and decisions.
- **Performance:** benchmark/evaluation data returned by the API.

All scenario data and map routes are synthetic/illustrative, not live operational feeds. Changing backend state is handled by the API and requires the appropriate user role.
