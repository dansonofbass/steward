import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/newsreader';
import '@fontsource/source-sans-3/400.css';
import '@fontsource/source-sans-3/600.css';
import App from './App';
import { followSky } from './lib/theme';
import './styles/fonts.css';
import './styles/tokens.css';
import './styles/sky.css';
import './styles/base.css';

followSky();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
