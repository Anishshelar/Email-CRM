import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Inbox from "./views/Inbox";
import ThreadWorkspace from "./views/ThreadWorkspace";
import Analytics from "./views/Analytics";

function NavItem({ to, label }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        `px-4 py-2 text-sm font-medium rounded transition-colors ${
          isActive
            ? "bg-accent-100 text-accent-700"
            : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
        }`
      }
    >
      {label}
    </NavLink>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col">
        <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-4">
          <span className="text-sm font-semibold text-gray-900 tracking-tight mr-4">
            SenAI CRM
          </span>
          <nav className="flex items-center gap-1">
            <NavItem to="/"          label="Inbox" />
            <NavItem to="/analytics" label="Analytics" />
          </nav>
        </header>
        <main className="flex-1 bg-gray-50">
          <Routes>
            <Route path="/"                element={<Inbox />} />
            <Route path="/thread/:emailId" element={<ThreadWorkspace />} />
            <Route path="/analytics"       element={<Analytics />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
