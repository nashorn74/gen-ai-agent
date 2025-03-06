// src/App.tsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { createTheme, ThemeProvider } from "@mui/material/styles";
import CssBaseline from "@mui/material/CssBaseline";

import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import ChatLayout from "./pages/ChatLayout";
import PrivateRoute from "./components/PrivateRoute";

function App() {
  // 임의로 Theme를 생성 (디자인 수정 가능)
  const theme = createTheme({
    palette: {
      mode: "light",
      primary: {
        main: "#1976d2",
      },
    },
  });

  const token = localStorage.getItem("token");
  const defaultRoute = token ? "/chat" : "/login";

  return (
    <ThemeProvider theme={theme}>
      {/* CssBaseline: 기본 reset/normalize + MUI 스타일 */}
      <CssBaseline />

      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to={defaultRoute} replace />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route
            path="/chat"
            element={
              <PrivateRoute>
                <ChatLayout />
              </PrivateRoute>
            }
          />
          <Route path="*" element={<div>Not Found</div>} />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;
