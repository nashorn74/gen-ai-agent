// src/pages/ChatLayout.tsx
import {
  useEffect, useState, useRef, useCallback, ChangeEvent, useLayoutEffect
} from "react";
import { useNavigate } from "react-router-dom";
import dayjs from "dayjs";
import {
  Box, Drawer, Toolbar, List, ListItemButton, ListItemText, Divider,
  AppBar, Typography, Button, TextField, Switch, FormControlLabel,
  ListSubheader, Dialog, DialogTitle, DialogContent, DialogActions,
  LinearProgress, IconButton, Paper, useTheme,
} from "@mui/material";
import { ThumbUp, ThumbDown } from "@mui/icons-material";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import ChatOutlinedIcon from "@mui/icons-material/ChatOutlined";
import ArticleOutlinedIcon from "@mui/icons-material/ArticleOutlined";
import { VariableSizeList, ListChildComponentProps } from "react-window";
import useResizeObserver from "../hooks/useResizeObserver";
import AutoSizer from "react-virtualized-auto-sizer";
import type { Size } from "react-virtualized-auto-sizer";
import { fetchWithAuth } from "../utils/api";
import ProfilingDialog from "../components/ProfilingDialog";

/* ---------- types ---------- */
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

/* =================================================================== */
export default function ChatLayout() {
  const navigate = useNavigate();
  const theme = useTheme();

  /* ---------- state ---------- */
  const [userName, setUserName]           = useState("");
  const [profileExists, setProfileExists] = useState(false);
  const [conversations, setConversations] = useState<any[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<number|null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputMode, setInputMode] = useState<"chat" | "summary">("chat");

  const [question,    setQuestion]    = useState("");
  const [searchMode,  setSearchMode]  = useState(false);
  const [uploadFile,  setUploadFile]  = useState<File|null>(null);
  const [isLoading,   setIsLoading]   = useState(false);

  const [agenda,      setAgenda]      = useState<AgendaEvent[]>([]);
  const [gcConnected, setGcConnected] = useState(false);

  /* ----- quick-event dialog ----- */
  const [openQuick,   setOpenQuick]   = useState(false);
  const [quickTitle,  setQuickTitle]  = useState("");
  const [quickDate,   setQuickDate]   = useState(dayjs().format("YYYY-MM-DD"));

  const [openProfileDlg, setOpenProfileDlg] = useState(false);

  /* ---------- virtualization refs ---------- */
  const listRef = useRef<VariableSizeList>(null);
  const sizeMap = useRef<{ [k:number]:number }>({});
  const getSize = (idx:number)=> sizeMap.current[idx] ?? 120;     // fallback height
  const setSize = (idx:number,h:number)=>{
    if (sizeMap.current[idx] !== h) {
      sizeMap.current = { ...sizeMap.current, [idx]: h };
      listRef.current?.resetAfterIndex(idx);
    }
  };

  /* =================================================================== */
  /*   1. 첫 로딩   */
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) { navigate("/login"); return; }

    /* 프로필 */
    fetchWithAuth("/profile")
      .then(()=> setProfileExists(true))
      .catch(err=>{
        if (err.status===404) { setProfileExists(false); setOpenProfileDlg(true); }
      });

    /* 사용자 · 대화 목록 · 일정 3일 */
    fetchWithAuth("/auth/me").then(d=> setUserName(d.username));
    fetchWithAuth("/chat/conversations").then(setConversations);

    const end = new Date(Date.now()+3*86400e3).toISOString();
    fetchWithAuth(`/events?end=${end}`).then(setAgenda);

    /* GCal 연결 여부 */
    fetchWithAuth("/gcal/status").then(d=> setGcConnected(d.connected));
  }, []);

  /*   2. 대화 선택 → 메시지 로딩   */
  useEffect(() => {
    if (!selectedConversation) { setMessages([]); return; }
    loadConversation(selectedConversation);
  }, [selectedConversation]);

  useEffect(() => {
    if (!messages.length || !listRef.current) return;
    // 마지막 행으로 스크롤 – 'end' 는 살짝 여유를 둬 깔끔
    listRef.current.scrollToItem(messages.length - 1, "end");
  }, [messages.length]);   // ← 메시지 개수 변할 때마다 실행

  /* ---------- helpers ---------- */
  const loadConversation = async (cid:number)=>{
    const d = await fetchWithAuth(`/chat/conversations/${cid}`);
    const sorted = [...d.messages].sort(
      (a,b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    );
    setMessages(sorted);
    sizeMap.current = {};
    listRef.current?.resetAfterIndex(0);
  };
  const loadConversationList = async ()=>{
    setConversations(await fetchWithAuth("/chat/conversations"));
  };
  const reloadAgenda = async ()=>{
    const end = new Date(Date.now()+3*86400e3).toISOString();
    setAgenda(await fetchWithAuth(`/events?end=${end}`));
  };
  const refreshGcalStatus = async ()=>{
    const { connected } = await fetchWithAuth("/gcal/status");
    setGcConnected(connected);
  };

  /* ---------- Google Calendar 연결/해제 ---------- */
  const toggleGoogle = async ()=>{
    if (!gcConnected) {
      const { auth_url } = await fetchWithAuth("/gcal/authorize");
      const popup = window.open(auth_url,"_blank","width=500,height=650");
      const handler = (e:MessageEvent)=>{
        if(e.data==="gcal_success"){ popup?.close(); window.removeEventListener("message",handler); refreshGcalStatus(); reloadAgenda(); }
      };
      window.addEventListener("message",handler);
    } else {
      setGcConnected(false); setAgenda([]);
      await fetchWithAuth("/gcal/disconnect",{method:"DELETE"}); refreshGcalStatus();
    }
  };

  /* ---------- 새로운 대화 ---------- */
  const newConversation = ()=>{
    setSelectedConversation(null);
    setMessages([]);
    sizeMap.current = {};
  };

  /* =================================================================== */
  /*   3. send() – 기존 REST 흐름 유지   */
  const send = async ()=>{
    if (!question.trim() || isLoading) return;
    setIsLoading(true);

    const endpoint = searchMode ? "/search" : "/chat";
    const payload  = {
      conversation_id: selectedConversation,
      question,
      query: question,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    };

    try{
      const data = await fetchWithAuth(endpoint,{ method:"POST", body:JSON.stringify(payload) });

      /* 대화 · 메시지 · 일정 다시 읽기 */
      if (data.conversation_id) {
        setSelectedConversation(data.conversation_id);
        await loadConversation(data.conversation_id);
        await loadConversationList();
        await reloadAgenda();
      }
    } finally {
      setIsLoading(false);
      setQuestion("");
    }
  };

  /* ---------- 파일 요약 ---------- */
  const summarize = async ()=>{
    if(!uploadFile) return;
    setIsLoading(true);

    const fd = new FormData();
    fd.append("file",uploadFile);
    if(selectedConversation) fd.append("conversation_id",String(selectedConversation));

    const data = await fetchWithAuth("/summarize",{method:"POST",body:fd});
    if(data.conversation_id) setSelectedConversation(data.conversation_id);

    let summaryText: string;

    if (typeof data.summary === "string" && data.summary.startsWith('"')) {
      // 따옴표로 둘러싸인 형태면 JSON.parse 시도
      try {
        summaryText = JSON.parse(data.summary)
                          .replace(/\\n/g, "\n")      // \n → 줄바꿈
                          .replace(/\\"/g, "\"");      // \" → "
      } catch {
        summaryText = data.summary;                   // 실패하면 원본 유지
      }
    } else {
      summaryText = String(data.summary);
    }

    const now = Date.now();
    setMessages(p=>[
      ...p,
      {message_id:now,role:"user",content:`[파일요약] ${uploadFile.name}`,created_at:new Date().toISOString()},
      {message_id:now+1,role:"assistant",content:summaryText,created_at:new Date().toISOString()},
    ]);
    setUploadFile(null);
    setIsLoading(false);
  };

  /* ---------- 피드백 ---------- */
  const sendCardFeedback = async (card_id:string,label:string)=>{
    await fetchWithAuth("/feedback",{method:"POST",body:JSON.stringify({
      category:"recommend",reference_id:`card_id=${card_id}`,feedback_label:label
    })});
    if(selectedConversation) loadConversation(selectedConversation);
  };
  const sendMessageFeedback = async (mid:number,label:string)=>{
    await fetchWithAuth("/feedback",{method:"POST",body:JSON.stringify({
      category:"chat",reference_id:`message_${mid}`,feedback_label:label
    })});
    if(selectedConversation) loadConversation(selectedConversation);
  };
  const iconColor = (current:string|undefined,target:string)=>(
    current===target ? (target==="like"?"success":"error") : "default"
  );

  /* =================================================================== */
  /*   4. react-window Row renderer   */
  const Row = useCallback(
    ({ index, style }: ListChildComponentProps) => {
      const m = messages[index];
      const isAssistant = m.role === "assistant";
  
      const rowStyle: React.CSSProperties = { ...style, width: "100%" };
      const measuredRef = useResizeObserver(rect => {
        const h = rect.height + 8;
        if (sizeMap.current[index] !== h) {
          sizeMap.current = { ...sizeMap.current, [index]: h };
          listRef.current?.resetAfterIndex(index);

          if (index === messages.length - 1) {
            listRef.current?.scrollToItem(index, "end");
          }
        }
      });
  
      return (
        <div style={rowStyle}>
          <Box ref={measuredRef} sx={{ px:1, py:0.5 }}>
            <Typography variant="subtitle2" color="text.secondary">
              {m.role}:
            </Typography>

          {m.cards?.length ? (
            <Box sx={{ mt:1, pl:2, borderLeft:`4px solid ${theme.palette.divider}` }}>
              {m.cards.map(card=>(
                <Box key={card.card_id} sx={{ mb:1 }}>
                  <Typography variant="subtitle1" fontWeight="bold">{card.title}</Typography>
                  {card.subtitle && <Typography variant="body2" color="text.secondary">{card.subtitle}</Typography>}
                  {card.link && (
                    <Button size="small" variant="outlined" onClick={()=>window.open(card.link,"_blank")}>자세히</Button>
                  )}
                  {card.reason && (
                    <Typography variant="caption" sx={{ display:"block", mt:0.5 }}>사유: {card.reason}</Typography>
                  )}
                  <Box sx={{ display:"flex", gap:0.5, mt:0.5 }}>
                    <IconButton
                      size="small"
                      color={iconColor(card.feedback?.feedback_label,"like")}
                      onClick={()=>sendCardFeedback(card.card_id,"like")}
                    ><ThumbUp fontSize="inherit" /></IconButton>
                    <IconButton
                      size="small"
                      color={iconColor(card.feedback?.feedback_label,"dislike")}
                      onClick={()=>sendCardFeedback(card.card_id,"dislike")}
                    ><ThumbDown fontSize="inherit" /></IconButton>
                  </Box>
                </Box>
              ))}
            </Box>
          ) : (
            <Typography
              whiteSpace="pre-line"
              sx={{ wordBreak:"break-word" }}
            >
              {m.content}
            </Typography>
          )}

          {isAssistant && (
            <Box sx={{ display:"flex", gap:0.5, mt:1 }}>
              <IconButton size="small" color={iconColor(m.feedback?.feedback_label,"like")}   onClick={()=>sendMessageFeedback(m.message_id,"like")}  ><ThumbUp   fontSize="inherit"/></IconButton>
              <IconButton size="small" color={iconColor(m.feedback?.feedback_label,"dislike")}onClick={()=>sendMessageFeedback(m.message_id,"dislike")}><ThumbDown fontSize="inherit"/></IconButton>
            </Box>
          )}
        </Box>
      </div>
    );
  },[messages]);

  /* =================================================================== */
  /*   5. render   */
  return (
    <Box sx={{ display:"flex", height:"100%", overflow:"hidden" }}>
      {/* ---------------- Drawer ---------------- */}
      <Drawer variant="permanent" sx={{ width:240,
        [`& .MuiDrawer-paper`]:{ width:240, top:64, boxSizing:"border-box" } }}>
        <Toolbar />
        <List>
          <ListItemButton sx={{ bgcolor:"action.hover" }} onClick={newConversation}>
            <ListItemText primary="새로운 대화 시작"/>
          </ListItemButton>
          <Divider />
          {conversations.map(c=>(
            <ListItemButton key={c.conversation_id}
              selected={c.conversation_id===selectedConversation}
              onClick={()=>setSelectedConversation(c.conversation_id)}>
              <ListItemText primary={c.title||`Conv ${c.conversation_id}`}/>
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
          {!agenda.length && <ListItemText sx={{ p:2 }} secondary="예정된 일정 없음"/>}

          {/* ─── 새로 추가된 “빠른 일정” 버튼 ─── */}
          <ListItemButton
            sx={{ mt:1, bgcolor:"action.hover" }}
            onClick={()=>setOpenQuick(true)}
          >
            <ListItemText primary="＋ 빠른 일정" />
          </ListItemButton>
        </List>
      </Drawer>

      {/* ---------------- Main ---------------- */}
      <Box sx={{ flex:1, display:"flex", flexDirection:"column", minWidth:0, 
        minHeight: 0, p:2, gap: 1
       }}>
        {/* AppBar */}
        <AppBar position="relative" color="default" sx={{ zIndex:1200 }}>
          <Toolbar>
            <Typography sx={{ flexGrow:1 }}>대화</Typography>
            <Button variant="outlined" onClick={toggleGoogle} sx={{ mr:2 }}>
              {gcConnected ? "Google 연결 해제" : "Google 연결"}
            </Button>
            <Typography sx={{ mr:2 }}>{userName}</Typography>
            {profileExists && <Button variant="outlined" sx={{ mr:2 }} onClick={()=>{ setProfileExists(false); setOpenProfileDlg(true); }}>프로필 편집</Button>}
            <Button onClick={()=>{ localStorage.removeItem("token"); navigate("/login"); }}>Logout</Button>
          </Toolbar>
        </AppBar>

        {isLoading && <LinearProgress />}

        {/* 메시지 영역 */}
        <Paper
          sx={{
            flex: "1 1 auto",   // column 내부에서 ‘가변(남는) 높이’ 영역
            minHeight: 0,       // 중요: react-window 가 정확히 height 계산
            overflow: "hidden",
          }}
        >
          {messages.length===0 ? (
            <Box sx={{ p:2 }}><Typography color="text.secondary">대화가 없습니다.</Typography></Box>
          ) : (
            <AutoSizer>
              {({ height, width }: Size) => (
                <VariableSizeList
                  ref={listRef}
                  height={height}
                  width={width}
                  itemCount={messages.length}
                  itemSize={getSize}
                  overscanCount={4}
                  itemKey={(index: number) => messages[index].message_id}
                >
                  {Row}
                </VariableSizeList>
              )}
            </AutoSizer>
          )}
        </Paper>

        {/* ────── 입력/요약 컨트롤 (1 줄) ────── */}
        <Box
          sx={{
            flex: "0 0 auto",   // 고정 높이
            display: "flex",
            gap: 1,
            alignItems: "center",
          }}
        >

        {/* 모드 아이콘 토글 */}
        <ToggleButtonGroup
          color="primary"
          value={inputMode}
          exclusive
          onChange={(_, v) => v && setInputMode(v)}
          size="small"
        >
          <ToggleButton value="chat"   sx={{ px:1 }} aria-label="채팅">
            <ChatOutlinedIcon fontSize="small" />
          </ToggleButton>
          <ToggleButton value="summary" sx={{ px:1 }} aria-label="문서 요약">
            <ArticleOutlinedIcon fontSize="small" />
          </ToggleButton>
        </ToggleButtonGroup>

        {/* ───────── chat 모드 ───────── */}
        {inputMode === "chat" && (
          <>
            <FormControlLabel
              sx={{ mr: 1,
                '.MuiFormControlLabel-label': {
                  fontSize: 12,          // 더 작은 글꼴
                  width: 32,             // 셀 너비 확보 (필요하면 36·40 으로 조절)
                  textAlign: 'center',
                  letterSpacing: '0.03em'
                }
               }}
              control={
                <Switch
                  size="small"
                  checked={searchMode}
                  onChange={e => setSearchMode(e.target.checked)}
                />
              }
              label="검색"
            />

            <TextField
              fullWidth
              size="small"
              label="메시지 입력"
              value={question}
              onChange={e => setQuestion(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") send(); }}
            />

            <Button
              variant="contained"
              onClick={send}
              disabled={isLoading || !question.trim()}
            >
              Send
            </Button>
          </>
        )}

        {/* ───────── summary 모드 ───────── */}
        {inputMode === "summary" && (
          <>
            <Button
              variant="outlined"
              component="label"
              size="small"
              disabled={isLoading}
            >
              파일
              <input
                hidden
                type="file"
                accept=".pdf,.txt"
                onChange={e => setUploadFile(e.target.files?.[0] || null)}
              />
            </Button>

            <Typography
              variant="body2"
              sx={{
                flex: 1,
                maxWidth: 240,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {uploadFile?.name || "선택된 파일 없음"}
            </Typography>

            <Button
              variant="contained"
              onClick={summarize}
              disabled={!uploadFile || isLoading}
            >
              요약
            </Button>
          </>
        )}
        </Box>
      </Box>

      {/* 빠른 일정 Dialog */}
      <Dialog open={openQuick} onClose={()=>setOpenQuick(false)}>
        <DialogTitle>빠른 일정 추가</DialogTitle>
        <DialogContent sx={{ display:"flex", flexDirection:"column", gap:2, mt:1 }}>
          <TextField label="제목" value={quickTitle} onChange={e=>setQuickTitle(e.target.value)} />
          <TextField type="date" label="날짜" InputLabelProps={{ shrink:true }} value={quickDate} onChange={e=>setQuickDate(e.target.value)} />
        </DialogContent>
        <DialogActions>
          <Button onClick={()=>setOpenQuick(false)}>취소</Button>
          <Button variant="contained" onClick={async()=>{ await quickSave(); }} disabled={!quickTitle.trim()}>저장</Button>
        </DialogActions>
      </Dialog>

      {/* 프로필 입력 다이얼로그 */}
      <ProfilingDialog
        open={openProfileDlg}
        onClose={()=>setOpenProfileDlg(false)}
        onSaved={()=>{ setProfileExists(true); setOpenProfileDlg(false); }}
      />
    </Box>
  );
}
