import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import Home from "@/pages/Home";
import Login from "@/pages/Login";
import Chat from "@/pages/Chat";
import StatusTracker from "@/pages/StatusTracker";
import NotFound from "@/pages/NotFound";

// Data fetching lives in src/lib/api.ts (plain fetch with timeouts and typed errors),
// so there is no query client to wire here.
export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/status" element={<StatusTracker />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
      <Toaster />
    </ErrorBoundary>
  );
}
