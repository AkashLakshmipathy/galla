import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";
import "./index.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    // The build id in the URL is what makes the browser notice a new worker at
    // all; without it a phone can sit on a months-old bundle indefinitely.
    navigator.serviceWorker
      .register(`/sw.js?v=${import.meta.env.VITE_BUILD_ID ?? "dev"}`)
      .catch(() => {
        /* an unregistered worker costs offline support, not the app */
      });

    let reloading = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      // A newer version has taken over. Reload once so the owner is not left
      // looking at yesterday's screens wondering why a fix did not arrive.
      if (reloading) return;
      reloading = true;
      window.location.reload();
    });
  });
}
