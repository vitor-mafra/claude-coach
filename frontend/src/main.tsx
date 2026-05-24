import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";

import App from "./App";
import { HttpError } from "./lib/api";
import "./index.css";

function redirectToLogin() {
  const path = window.location.pathname + window.location.search;
  if (window.location.pathname !== "/login") {
    const next = encodeURIComponent(path);
    window.location.replace(`/login?next=${next}`);
  }
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError(error) {
      if (error instanceof HttpError && error.status === 401) {
        redirectToLogin();
      }
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (count, error) => {
        if (error instanceof HttpError && error.status === 401) return false;
        return count < 1;
      },
    },
    mutations: {
      onError(error) {
        if (error instanceof HttpError && error.status === 401) {
          redirectToLogin();
        }
      },
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
