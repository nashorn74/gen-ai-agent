import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Box,
  AppBar,
  Toolbar,
  Typography,
  Button,
  Drawer,
  List,
  ListItemButton,
  ListItemText,
  Divider,
  Paper,
  TextField
} from "@mui/material";

interface Message {
  message_id: number;
  role: string;
  content: string;
  created_at: string;
}

function ChatLayout() {
  const navigate = useNavigate();
  const [userName, setUserName] = useState("");
  const [conversations, setConversations] = useState<any[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;

    // 1) me
    fetch("http://localhost:8000/auth/me", {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(res.statusText)))
      .then((data) => setUserName(data.username))
      .catch((err) => console.error("get me:", err));

    // 2) conversation list
    fetch("http://localhost:8000/chat/conversations", {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(res.statusText)))
      .then((data) => setConversations(data))
      .catch((err) => console.error("get convos:", err));
  }, []);

  // load conversation detail
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;
    if (!selectedConversation) {
      setMessages([]);
      return;
    }
    fetch(`http://localhost:8000/chat/conversations/${selectedConversation}`, {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(res.statusText)))
      .then((data) => setMessages(data.messages))
      .catch((err) => console.error(err));
  }, [selectedConversation]);

  const handleLogout = () => {
    localStorage.removeItem("token");
    navigate("/login");
  };

  const handleAsk = async () => {
    const token = localStorage.getItem("token");
    if (!token) return;
    try {
      const res = await fetch("http://localhost:8000/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          conversation_id: selectedConversation,
          question
        })
      });
      if (!res.ok) {
        throw new Error(`Chat error: ${res.status}`);
      }
      const data = await res.json();

      // 클라이언트 측에 메시지 반영
      const userMsg: Message = {
        message_id: Date.now(),
        role: "user",
        content: question,
        created_at: new Date().toISOString()
      };
      const assistantMsg: Message = {
        message_id: Date.now() + 1,
        role: "assistant",
        content: data.answer,
        created_at: new Date().toISOString()
      };

      if (data.conversation_id) {
        setSelectedConversation(data.conversation_id);
      }

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setQuestion("");
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <Box sx={{ display: "flex", height: "100vh" }}>
      {/* 상단 바 */}
      <AppBar position="fixed">
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Chat App
          </Typography>
          <Typography sx={{ mr: 2 }}>{userName}</Typography>
          <Button color="inherit" onClick={handleLogout}>
            Logout
          </Button>
        </Toolbar>
      </AppBar>

      {/* 왼쪽 Drawer (대화 목록) */}
      <Drawer
        variant="permanent"
        sx={{
          width: 240,
          flexShrink: 0,
          [`& .MuiDrawer-paper`]: {
            width: 240,
            top: "64px", // AppBar 높이, 만약 position fixed
            boxSizing: "border-box"
          }
        }}
      >
        <Toolbar />
        <Box sx={{ overflow: "auto" }}>
          <List>
            {conversations.map((c) => (
              <ListItemButton
                key={c.conversation_id}
                selected={c.conversation_id === selectedConversation}
                onClick={() => setSelectedConversation(c.conversation_id)}
              >
                <ListItemText
                  primary={c.title || `Conv ${c.conversation_id}`}
                />
              </ListItemButton>
            ))}
          </List>
        </Box>
      </Drawer>

      {/* 메인 영역 */}
      <Box sx={{ flexGrow: 1, marginTop: 8, p: 2 }}>
        {!selectedConversation && (
          <Typography>Select a conversation or ask a question to start.</Typography>
        )}

        {selectedConversation && (
          <>
            <Paper sx={{ mb: 2, height: "60vh", overflowY: "auto", p: 2 }}>
              {messages.map((m) => (
                <Box key={m.message_id} sx={{ mb: 1 }}>
                  <Typography variant="subtitle2" color="text.secondary">
                    {m.role}:
                  </Typography>
                  <Typography>{m.content}</Typography>
                  <Divider sx={{ my: 1 }} />
                </Box>
              ))}
            </Paper>

            <Box sx={{ display: "flex", gap: 1 }}>
              <TextField
                fullWidth
                label="Ask something..."
                variant="outlined"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
              />
              <Button variant="contained" onClick={handleAsk}>
                Send
              </Button>
            </Box>
          </>
        )}
      </Box>
    </Box>
  );
}

export default ChatLayout;
