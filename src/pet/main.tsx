import { createRoot } from 'react-dom/client';

import { PetApp } from './PetApp';
<<<<<<< HEAD
import './pet.css';

const root = document.getElementById('pet-root');
if (root) {
  createRoot(root).render(<PetApp />);
=======
import { PetPanelApp } from './PetPanelApp';
import './pet.css';

const root = document.getElementById('pet-root');
// The standalone panel window loads pet.html?panel=1 and renders only the
// status panel; the overlay window keeps the sprite.
const isPanelWindow = new URLSearchParams(window.location.search).get('panel') === '1';
if (isPanelWindow) {
  document.documentElement.classList.add('pet-panel-window');
}
if (root) {
  createRoot(root).render(isPanelWindow ? <PetPanelApp /> : <PetApp />);
>>>>>>> origin/main
}
