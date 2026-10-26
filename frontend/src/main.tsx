import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { LocationProvider } from "./state/location";
import { MapsProvider } from "./state/maps";
import { SessionProvider } from "./state/session";
import "./styles.css";

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <BrowserRouter basename="/app">
        <SessionProvider>
          <MapsProvider>
            <LocationProvider>
              <App />
            </LocationProvider>
          </MapsProvider>
        </SessionProvider>
      </BrowserRouter>
    </StrictMode>,
  );
}
