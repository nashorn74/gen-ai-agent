import { useEffect, useState, ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import dayjs from "dayjs";
import {
  Box, Drawer, Toolbar, List, ListItemButton, ListItemText, Divider,
  AppBar, Typography, Button, Paper, TextField, Switch, FormControlLabel,
  ListSubheader, Dialog, DialogTitle, DialogContent, DialogActions,
  LinearProgress, IconButton
} from "@mui/material";
import { ThumbUp, ThumbDown } from "@mui/icons-material";
import { fetchWithAuth } from "../utils/api";

interface FeedbackInfo {
  feedback_id?: number;
  feedback_score?: number;
  feedback_label?: string;
  details?: any;
}

interface RecommendCard {
  card_id: string;
  type: string;
  title: string;
  subtitle?: string;
  link?: string;
  reason?: string;
  score?: number;
  feedback?: FeedbackInfo | null;
}
interface Message {
  message_id: number;
  role: string;
  content: string;
  created_at: string;
  cards?: RecommendCard[];
  feedback?: FeedbackInfo | null;
}
interface AgendaEvent {
  id: string;
  summary: string;
  start: { dateTime?: string; date?: string };
}

export default function ChatLayout() {
  const navigate = useNavigate();

  // ───────── 상태 ─────────
  const [userName, setUserName]           = useState("");
  const [conversations, setConversations] = useState<any[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<number|null>(null);
  const [messages, setMessages] = useState<Message[]>([]);

  const [question,    setQuestion]    = useState("");
  const [searchMode,  setSearchMode]  = useState(false);
  const [uploadFile,  setUploadFile]  = useState<File|null>(null);
  const [isLoading,   setIsLoading]   = useState(false);

  const [agenda,      setAgenda]      = useState<AgendaEvent[]>([]);
  const [gcConnected, setGcConnected] = useState(false);

  // ─── 빠른 일정 Dialog ───
  const [openQuick,   setOpenQuick]   = useState(false);
  const [quickTitle,  setQuickTitle]  = useState("");
  const [quickDate,   setQuickDate]   = useState(dayjs().format("YYYY-MM-DD"));

  // ───────── 최초 로딩 ─────────
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) { navigate("/login"); return; }

    // 사용자 정보
    fetchWithAuth("/auth/me").then(d => setUserName(d.username));

    // 대화 목록
    fetchWithAuth("/chat/conversations").then(setConversations);

    // 3일치 일정
    const end = new Date(Date.now() + 3*86400*1000).toISOString();
    fetchWithAuth(`/events?end=${end}`).then(setAgenda);

    // Google 연결 여부
    fetchWithAuth("/gcal/status").then(d => setGcConnected(d.connected));
  }, []);

  // ─── 대화 선택 → 메시지 불러오기 ───
  useEffect(() => {
    if (!selectedConversation) {
      setMessages([]);
      return;
    }
    loadConversation(selectedConversation);
  }, [selectedConversation]);

  // ───────── Helper: 대화/목록 로더 ─────────
  const loadConversation = async (convId:number) => {
    const d = await fetchWithAuth(`/chat/conversations/${convId}`);
    setMessages(d.messages);
  };
  const loadConversationList = async () => {
    const list = await fetchWithAuth("/chat/conversations");
    setConversations(list);
  };

  // ─── Drawer Helper ───
  const reloadAgenda = async () => {
    const end = new Date(Date.now() + 3*86400*1000).toISOString();
    setAgenda(await fetchWithAuth(`/events?end=${end}`));
  };

  const refreshGcalStatus = async () => {
    const { connected } = await fetchWithAuth("/gcal/status");
    setGcConnected(connected);
  };

  // ───────── Google Calendar 연결 / 해제 ─────────
  const toggleGoogle = async () => {
    if (!gcConnected) {
      const { auth_url } = await fetchWithAuth("/gcal/authorize");
      const popup = window.open(auth_url, "_blank", "width=500,height=650");
      const handler = (e: MessageEvent) => {
        if (e.data === "gcal_success") {
          popup?.close();
          window.removeEventListener("message", handler);
          refreshGcalStatus();
          reloadAgenda();
        }
      };
      window.addEventListener("message", handler);
    } else {
      setGcConnected(false);
      setAgenda([]);
      
      await fetchWithAuth("/gcal/disconnect", { method: "DELETE" });
      refreshGcalStatus();      
    }
  };

  const quickSave = async () => {
    if (!quickTitle) return;           // 제목이 없으면 무시
    setIsLoading(true);
  
    const token = localStorage.getItem("token")!;
    const start = dayjs(quickDate).hour(9).minute(0).second(0);
    const end   = start.add(1, "hour");
  
    await fetch("http://localhost:8000/events", {
      method : "POST",
      headers: {
        "Content-Type" : "application/json",
        Authorization  : `Bearer ${token}`,
      },
      body: JSON.stringify({
        summary : quickTitle,
        start   : start.toISOString(),
        end     : end  .toISOString(),
        timezone: "Europe/Berlin",
      }),
    });
  
    // 새 일정이 저장됐으니 3‑일 미리보기 다시 읽기
    const until = new Date(Date.now() + 3*24*60*60*1000).toISOString();
    const mini  = await fetchWithAuth(`/events?end=${until}`);
    setAgenda(mini);
  
    setQuickTitle("");
    setOpenQuick(false);
    setIsLoading(false);
  };

  // ─── 새 대화 ───
  const newConversation = () => {
    setSelectedConversation(null);
    setMessages([]);
  };

  // ─── 채팅 / 검색 요청 ───
  const send = async () => {
    if (!question.trim()) return;

    setIsLoading(true);
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone; // ex. "Europe/Berlin"
    const endpoint = searchMode ? "/search" : "/chat";
    const payload: any = {
      conversation_id : selectedConversation,
      question        : question,
      timezone        : tz,
    };

    const data = await fetchWithAuth(endpoint, { method:"POST", body:JSON.stringify(payload)});
    if (data.conversation_id) {
      // 업데이트: 선택대화 설정
      setSelectedConversation(data.conversation_id);
      // 메시지 목록 재로딩
      await loadConversation(data.conversation_id);
      // 대화 목록도 재로딩 (제목이 바뀌었을 수 있으니까)
      await loadConversationList();
    }

    setQuestion("");
    setIsLoading(false);
  };

  // ─── 파일 요약 ───
  const summarize = async () => {
    if (!uploadFile) return;
    setIsLoading(true);
    const fd = new FormData();
    fd.append("file", uploadFile);
    if (selectedConversation) fd.append("conversation_id", String(selectedConversation));
    const data = await fetchWithAuth("/summarize", { method:"POST", body:fd, raw:true });
    if (data.conversation_id) setSelectedConversation(data.conversation_id);

    const now = Date.now();
    setMessages(p => [
      ...p,
      {message_id:now,   role:"user",      content:`[파일요약] ${uploadFile.name}`, created_at:new Date().toISOString()},
      {message_id:now+1, role:"assistant", content:data.summary,                    created_at:new Date().toISOString()}
    ]);
    setUploadFile(null);
    setIsLoading(false);
  };

  // ★ 추가: 카드 피드백 전송 함수
  const sendCardFeedback = async (card_id:string, label:string) => {
    // POST /feedback (category="recommend", reference_id=`card_id=${card_id}`, feedback_label=label)
    const body = {
      category: "recommend",
      reference_id: `card_id=${card_id}`,
      feedback_label: label
    };
    try {
      await fetchWithAuth("/feedback", {
        method: "POST",
        body: JSON.stringify(body)
      });
      // TODO: 업데이트된 피드백을 반영하기 위해, 대화 다시 로드 or 해당 메시지만 업데이트
      if (selectedConversation) {
        const data = await fetchWithAuth(`/chat/conversations/${selectedConversation}`);
        setMessages(data.messages);
      }
    } catch(e) {
      console.error(e);
    }
  };

  // 메시지 피드백
  const sendMessageFeedback = async (message_id:number, label:string) => {
    // POST /feedback (category="chat", reference_id=`message_${message_id}`, feedback_label=label)
    const body = {
      category: "chat",
      reference_id: `message_${message_id}`,
      feedback_label: label
    };
    try {
      await fetchWithAuth("/feedback", {
        method: "POST",
        body: JSON.stringify(body)
      });
      if (selectedConversation) {
        const data = await fetchWithAuth(`/chat/conversations/${selectedConversation}`);
        setMessages(data.messages);
      }
    } catch(e) {
      console.error(e);
    }
  };

  // ---- 아이콘 색상 구분 함수 (★추가)
  const iconColor = (currentLabel: string|undefined, targetLabel:string) => {
    if (currentLabel === targetLabel) {
      // 좋아요 선택 => 녹색, 싫어요 선택 => 빨간색
      return (targetLabel==="like") ? "success" : "error";
    }
    return "default";
  };

  // ───────── 렌더링 ─────────
  return (
    <Box sx={{ display:"flex", height:"100vh", overflow:"hidden" }}>
      {/* ─── Drawer ─── */}
      <Drawer variant="permanent" sx={{width:240,
        [`& .MuiDrawer-paper`]:{width:240, top:64, boxSizing:"border-box"}}}>
        <Toolbar />
        <List>
          <ListItemButton sx={{bgcolor:"#f5f5f5"}} onClick={newConversation}>
            <ListItemText primary="새로운 대화 시작"/>
          </ListItemButton>
          <Divider />
          {conversations.map(c=>(
            <ListItemButton key={c.conversation_id}
              selected={c.conversation_id===selectedConversation}
              onClick={()=>setSelectedConversation(c.conversation_id)}>
              <ListItemText primary={c.title||`Conv ${c.conversation_id}`} />
            </ListItemButton>
          ))}
        </List>
        <Divider />
        <List subheader={<ListSubheader>다가오는 일정</ListSubheader>}>
          {agenda.map(ev=>(
            <ListItemButton key={ev.id} onClick={()=>navigate(`/calendar?e=${ev.id}`)}>
              <ListItemText
                primary={ev.summary}
                secondary={dayjs(ev.start.dateTime||ev.start.date).format("DD HH:mm")}
              />
            </ListItemButton>
          ))}
          {agenda.length===0 && (
            <ListItemText sx={{p:2}} secondary="예정된 일정 없음"/>
          )}
        </List>
      </Drawer>

      {/* ─── Main ─── */}
      <Box sx={{ flex:1, display:"flex", flexDirection:"column", minWidth:0 }}>
        <AppBar position="relative" color="default" sx={{ zIndex:1200 }}>
          <Toolbar>
            <Typography sx={{ flexGrow:1 }}>대화</Typography>
            <Button variant="outlined" onClick={toggleGoogle} sx={{mr:2}}>
              {gcConnected ? "Google 연결 해제" : "Google 연결"}
            </Button>
            <Typography sx={{mr:2}}>{userName}</Typography>
            <Button onClick={()=>{localStorage.removeItem("token");navigate("/login");}}>
              Logout
            </Button>
          </Toolbar>
        </AppBar>

        {isLoading && <LinearProgress />}

        <Paper sx={{ height: '60vh', m:2, p:2, overflowY:"auto" }}>
          {messages.length===0
            ? <Typography color="text.secondary">대화가 없습니다.</Typography>
            : messages.map(m=>{
              const isAssistant = (m.role==="assistant"); // ★ user=질문은 피드백X
              return (
                <Box key={m.message_id} sx={{mb:1}}>
                  <Typography variant="subtitle2" color="text.secondary">{m.role}:</Typography>

                  {/* 메시지가 어시스턴트(답변)일때만 피드백 */}
                  {isAssistant && (
                    <Box sx={{display:"flex", gap:1, mt:1}}>
                      <IconButton
                        color={iconColor(m.feedback?.feedback_label,"like")}
                        onClick={()=>sendMessageFeedback(m.message_id,"like")}
                      >
                        <ThumbUp fontSize="small" />
                      </IconButton>
                      <IconButton
                        color={iconColor(m.feedback?.feedback_label,"dislike")}
                        onClick={()=>sendMessageFeedback(m.message_id,"dislike")}
                      >
                        <ThumbDown fontSize="small" />
                      </IconButton>
                    </Box>
                  )}

                  {m.cards && m.cards.length>0 ? (
                    <Box sx={{mt:1, mb:1, pl:2, borderLeft:"4px solid #ddd"}}>
                      {m.cards.map(card=>(
                        <Box key={card.card_id} sx={{mb:1}}>
                          <Typography variant="subtitle1" fontWeight="bold">{card.title}</Typography>
                          {card.subtitle && (
                            <Typography variant="body2" color="text.secondary">
                              {card.subtitle}
                            </Typography>
                          )}
                          {card.link && (
                            <Button size="small" variant="outlined"
                              onClick={()=>window.open(card.link,"_blank")}>
                              자세히
                            </Button>
                          )}
                          {card.reason && (
                            <Typography variant="caption" sx={{display:"block",mt:0.5}}>
                              사유: {card.reason}
                            </Typography>
                          )}
                          
                          {/* ---- 카드 피드백 */}
                          <Box sx={{display:"flex", gap:1, mt:1}}>
                            <IconButton
                              color={iconColor(card.feedback?.feedback_label,"like")}
                              onClick={()=>sendCardFeedback(card.card_id, "like")}
                            >
                              <ThumbUp fontSize="small" />
                            </IconButton>
                            <IconButton
                              color={iconColor(card.feedback?.feedback_label,"dislike")}
                              onClick={()=>sendCardFeedback(card.card_id, "dislike")}
                            >
                              <ThumbDown fontSize="small" />
                            </IconButton>
                          </Box>
                        </Box>
                      ))}
                    </Box>
                  ) : (
                    <Typography whiteSpace="pre-line">{m.content}</Typography>
                  )}
                  <Divider sx={{my:1}}/>
                </Box>
              );
            })}
        </Paper>

        {/* 입력 */}
        <Box sx={{m:2, display:"flex", gap:1}}>
          <FormControlLabel control={
            <Switch checked={searchMode} onChange={e=>setSearchMode(e.target.checked)}/>
          } label="정보검색"/>
          <TextField fullWidth label="메시지 입력" value={question}
            onChange={e=>setQuestion(e.target.value)}
            onKeyDown={e=>{if(e.key==="Enter") send();}}/>
          <Button variant="contained" onClick={send} disabled={isLoading}>Send</Button>
        </Box>

        {/* 파일 & 빠른 일정 */}
        <Box sx={{m:2, display:"flex", gap:1}}>
          <Button variant="outlined" component="label" disabled={isLoading}>
            파일 선택
            <input hidden type="file" accept=".pdf,.txt" onChange={(e:ChangeEvent<HTMLInputElement>)=>{
              setUploadFile(e.target.files?.[0]||null);
            }}/>
          </Button>
          <Typography variant="body2" sx={{flex:1}}>
            {uploadFile ? uploadFile.name : "선택된 파일 없음"}
          </Typography>
          <Button variant="contained" disabled={!uploadFile||isLoading} onClick={summarize}>
            문서 요약
          </Button>
          <Button variant="outlined" onClick={()=>setOpenQuick(true)}>빠른 일정</Button>
        </Box>
      </Box>

      {/* 빠른 일정 Dialog */}
      <Dialog open={openQuick} onClose={()=>setOpenQuick(false)}>
        <DialogTitle>빠른 일정 추가</DialogTitle>
        <DialogContent sx={{display:"flex",flexDirection:"column",gap:2,mt:1}}>
          <TextField label="제목" value={quickTitle}
            onChange={e=>setQuickTitle(e.target.value)}/>
          <TextField type="date" label="날짜" InputLabelProps={{shrink:true}}
            value={quickDate} onChange={e=>setQuickDate(e.target.value)}/>
        </DialogContent>
        <DialogActions>
          <Button onClick={()=>setOpenQuick(false)}>취소</Button>
          <Button onClick={quickSave} disabled={!quickTitle}>
            저장
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
