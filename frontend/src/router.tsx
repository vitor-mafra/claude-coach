import { createRouter } from "@tanstack/react-router";

import {
  Route as briefingRoute,
  DetailRoute as briefingDetailRoute,
} from "./routes/briefing";
import { Route as exercisesRoute } from "./routes/exercises";
import {
  Route as reportsRoute,
  DetailRoute as reportDetailRoute,
} from "./routes/reports";
import { Route as historyRoute } from "./routes/history";
import { Route as homeRoute } from "./routes/index";
import { Route as loginRoute } from "./routes/login";
import { Route as planDetailRoute } from "./routes/plan-detail";
import { Route as plansRoute } from "./routes/plans";
import { Route as profileRoute } from "./routes/profile";
import { Route as sessionDetailRoute } from "./routes/session-detail";
import { Route as sessionNewRoute } from "./routes/session-new";
import { Route as usageRoute } from "./routes/usage";
import { Route as rootRoute } from "./routes/__root";

const routeTree = rootRoute.addChildren([
  homeRoute,
  plansRoute,
  planDetailRoute,
  exercisesRoute,
  profileRoute,
  usageRoute,
  sessionNewRoute,
  sessionDetailRoute,
  historyRoute,
  briefingRoute,
  briefingDetailRoute,
  reportsRoute,
  reportDetailRoute,
  loginRoute,
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
