// src/socket.ts
var logger = {
  info: (message, ...args) => {
    console.log(`[INFO] ${message}`, ...args);
  },
  debug: (message, ...args) => {
    console.log(`[DEBUG] ${message}`, ...args);
  },
  warn: (message, ...args) => {
    console.warn(`[WARN] ${message}`, ...args);
  },
  error: (message, ...args) => {
    console.error(`[ERROR] ${message}`, ...args);
  }
};
var channels = /* @__PURE__ */ new Map();
var stats = {
  totalConnections: 0,
  activeConnections: 0,
  messagesSent: 0,
  messagesReceived: 0,
  errors: 0,
  // Queue & routing stats
  queueDepthMax: 0,
  queuedCommands: 0,
  queueRejections: 0,
  blockedCommands: 0,
  unicastResponses: 0,
  discardedResponses: 0,
  cleanedStaleRequests: 0
};
var requestToClient = /* @__PURE__ */ new Map();
var pluginClients = /* @__PURE__ */ new Set();
var agentClients = /* @__PURE__ */ new Set();
var sessionToClient = /* @__PURE__ */ new Map();
var CREATION_COMMANDS = /* @__PURE__ */ new Set([
  "create_rectangle",
  "create_frame",
  "create_text",
  "create_ellipse",
  "create_polygon",
  "create_star",
  "create_vector",
  "create_line",
  "create_component_instance",
  "create_component_set",
  "set_svg",
  "clone_node",
  "create_component_from_node",
  // FigJam creation commands
  "create_section",
  "create_sticky",
  "create_shape_with_text",
  "create_connector"
]);
var BLOCKED_COMMANDS = /* @__PURE__ */ new Set(["set_current_page"]);
var COMMAND_TIMEOUT_MS = 12e4;
var channelQueues = /* @__PURE__ */ new Map();
var MAX_QUEUE_SIZE = 100;
function getPluginClient(channelName) {
  const clients = channels.get(channelName);
  if (!clients) return null;
  for (const client of clients) {
    if (pluginClients.has(client)) return client;
  }
  return null;
}
function validateCommand(data, channelName) {
  const command = data.message?.command;
  const params = data.message?.params;
  if (BLOCKED_COMMANDS.has(command)) {
    return `"${command}" is a stateful command and is not allowed through the relay server. Instead, use the parentId parameter on creation commands to target a specific page or frame. Call get_pages to discover page node IDs, then pass the desired page ID as parentId.`;
  }
  if (CREATION_COMMANDS.has(command) && !params?.parentId) {
    return `"${command}" requires a parentId parameter. Pass the target page or frame node ID as parentId to specify where the element should be created. Call get_pages to discover available page IDs.`;
  }
  return null;
}
function classifyClient(ws, data) {
  if (pluginClients.has(ws) || agentClients.has(ws)) return;
  if (data.message?.result !== void 0 || data.message?.error !== void 0) {
    pluginClients.add(ws);
    logger.info(`Client ${ws.data?.clientId} classified as Figma plugin`);
    return;
  }
  if (data.message?.command) {
    agentClients.add(ws);
    logger.info(`Client ${ws.data?.clientId} classified as MCP agent`);
    return;
  }
}
function ensureQueueState(channelName) {
  if (!channelQueues.has(channelName)) {
    channelQueues.set(channelName, { queue: [], isProcessing: false });
  }
  return channelQueues.get(channelName);
}
function enqueueCommand(data, ws, channelName) {
  const requestId = data.message?.id;
  if (!requestId) {
    logger.warn("Command missing message.id, cannot queue");
    return;
  }
  const queueState = ensureQueueState(channelName);
  if (queueState.queue.length >= MAX_QUEUE_SIZE) {
    ws.send(JSON.stringify({
      type: "broadcast",
      message: {
        id: requestId,
        error: `Command queue is full (${MAX_QUEUE_SIZE} pending commands). Wait for existing commands to complete.`
      },
      sender: "You",
      channel: channelName
    }));
    stats.queueRejections++;
    stats.messagesSent++;
    return;
  }
  requestToClient.set(requestId, { ws, timestamp: Date.now() });
  queueState.queue.push({
    data,
    senderWs: ws,
    requestId,
    enqueuedAt: Date.now()
  });
  stats.queuedCommands++;
  if (queueState.queue.length > stats.queueDepthMax) {
    stats.queueDepthMax = queueState.queue.length;
  }
  const depth = queueState.queue.length;
  if (depth > 50) {
    logger.warn(`Queue depth warning: ${depth} commands pending in channel ${channelName}`);
  }
  processQueue(channelName);
}
function processQueue(channelName) {
  const queueState = channelQueues.get(channelName);
  if (!queueState || queueState.isProcessing || queueState.queue.length === 0) return;
  queueState.isProcessing = true;
  const item = queueState.queue.shift();
  const pluginClient = getPluginClient(channelName);
  const payload = JSON.stringify({
    type: "broadcast",
    message: item.data.message,
    sender: "User",
    channel: channelName
  });
  let forwarded = false;
  if (pluginClient && pluginClient.readyState === WebSocket.OPEN) {
    try {
      pluginClient.send(payload);
      stats.messagesSent++;
      forwarded = true;
    } catch (error) {
      logger.error(`Failed to forward command to plugin:`, error);
      stats.errors++;
    }
  } else {
    const clients = channels.get(channelName);
    if (clients) {
      for (const client of clients) {
        if (!agentClients.has(client) && client.readyState === WebSocket.OPEN) {
          try {
            client.send(payload);
            stats.messagesSent++;
            forwarded = true;
          } catch (error) {
            logger.error(`Failed to forward command to non-agent client:`, error);
          }
        }
      }
    }
  }
  if (!forwarded) {
    logger.warn(`No plugin client in channel ${channelName}, rejecting queued command`);
    if (item.senderWs.readyState === WebSocket.OPEN) {
      item.senderWs.send(JSON.stringify({
        type: "broadcast",
        message: { id: item.requestId, error: "No Figma plugin connected to this channel" },
        sender: "You",
        channel: channelName
      }));
      stats.messagesSent++;
    }
    requestToClient.delete(item.requestId);
    queueState.isProcessing = false;
    setTimeout(() => processQueue(channelName), 0);
    return;
  }
  queueState.currentRequestId = item.requestId;
  queueState.currentCommandTimeout = setTimeout(() => {
    if (queueState.currentRequestId !== item.requestId) return;
    logger.warn(`Command ${item.requestId} timed out after ${COMMAND_TIMEOUT_MS}ms in channel ${channelName}`);
    const entry = requestToClient.get(item.requestId);
    if (entry && entry.ws.readyState === WebSocket.OPEN) {
      try {
        entry.ws.send(JSON.stringify({
          type: "broadcast",
          message: { id: item.requestId, error: "Command timed out waiting for Figma plugin response" },
          sender: "User",
          channel: channelName
        }));
        stats.messagesSent++;
      } catch (e) {
        logger.error(`Failed to send timeout error:`, e);
      }
    }
    requestToClient.delete(item.requestId);
    queueState.isProcessing = false;
    queueState.currentCommandTimeout = void 0;
    queueState.currentRequestId = void 0;
    processQueue(channelName);
  }, COMMAND_TIMEOUT_MS);
  if (item.senderWs.readyState === WebSocket.OPEN) {
    try {
      item.senderWs.send(JSON.stringify({
        type: "broadcast",
        message: item.data.message,
        sender: "You",
        channel: channelName
      }));
      stats.messagesSent++;
    } catch (error) {
      logger.error(`Failed to send command echo to sender:`, error);
    }
  }
  queueState.queue.forEach((waiting, index) => {
    if (waiting.senderWs.readyState === WebSocket.OPEN) {
      try {
        waiting.senderWs.send(JSON.stringify({
          type: "queue_position",
          id: waiting.requestId,
          position: index + 1,
          queueSize: queueState.queue.length,
          message: {
            data: {
              status: "queued",
              progress: 0,
              message: `Queued at position ${index + 1} of ${queueState.queue.length}`
            }
          }
        }));
        stats.messagesSent++;
      } catch (error) {
        logger.error(`Failed to send queue position update:`, error);
      }
    }
  });
}
function handleResponseFromPlugin(data, channelName) {
  const responseId = data.message?.id;
  const entry = responseId ? requestToClient.get(responseId) : null;
  if (entry && entry.ws.readyState === WebSocket.OPEN) {
    try {
      entry.ws.send(JSON.stringify({
        type: "broadcast",
        message: data.message,
        sender: "User",
        channel: channelName
      }));
      stats.unicastResponses++;
      stats.messagesSent++;
    } catch (error) {
      logger.error(`Failed to unicast response:`, error);
      stats.errors++;
    }
    requestToClient.delete(responseId);
  } else {
    if (responseId) {
      logger.info(`Discarding orphaned response for request ${responseId} (sender disconnected)`);
      requestToClient.delete(responseId);
    } else {
      logger.info(`Discarding untracked response (no request ID)`);
    }
    stats.discardedResponses++;
  }
  const queueState = channelQueues.get(channelName);
  if (queueState && responseId && responseId === queueState.currentRequestId) {
    if (queueState.currentCommandTimeout) {
      clearTimeout(queueState.currentCommandTimeout);
      queueState.currentCommandTimeout = void 0;
    }
    queueState.currentRequestId = void 0;
    queueState.isProcessing = false;
    processQueue(channelName);
  }
}
function cleanupClient(ws, clientChannels = []) {
  const isPlugin = pluginClients.has(ws);
  if (isPlugin) {
    const channelsToCheck = clientChannels.length > 0 ? clientChannels : Array.from(channelQueues.keys());
    for (const channelName of channelsToCheck) {
      const queueState = channelQueues.get(channelName);
      if (!queueState) continue;
      if (queueState.isProcessing && queueState.currentRequestId) {
        const requestId = queueState.currentRequestId;
        logger.warn(`Plugin disconnected while command ${requestId} was in-flight on channel ${channelName}`);
        if (queueState.currentCommandTimeout) {
          clearTimeout(queueState.currentCommandTimeout);
          queueState.currentCommandTimeout = void 0;
        }
        const entry = requestToClient.get(requestId);
        if (entry && entry.ws.readyState === WebSocket.OPEN) {
          try {
            entry.ws.send(JSON.stringify({
              type: "broadcast",
              message: { id: requestId, error: "Figma plugin disconnected while processing command" },
              sender: "User",
              channel: channelName
            }));
            stats.messagesSent++;
          } catch (e) {
            logger.error(`Failed to send plugin disconnect error:`, e);
          }
        }
        requestToClient.delete(requestId);
        queueState.isProcessing = false;
        queueState.currentRequestId = void 0;
        setTimeout(() => processQueue(channelName), 0);
      }
    }
  }
  if (!isPlugin) {
    for (const [requestId, entry] of requestToClient.entries()) {
      if (entry.ws === ws) {
        requestToClient.delete(requestId);
      }
    }
  }
  for (const [channelName, queueState] of channelQueues.entries()) {
    const before = queueState.queue.length;
    queueState.queue = queueState.queue.filter((item) => {
      if (item.senderWs === ws) {
        logger.info(`Removing queued command ${item.requestId} from disconnected client`);
        requestToClient.delete(item.requestId);
        return false;
      }
      return true;
    });
    const removed = before - queueState.queue.length;
    if (removed > 0) {
      logger.info(`Cleaned up ${removed} queued commands from disconnected client in channel ${channelName}`);
    }
  }
  agentClients.delete(ws);
  pluginClients.delete(ws);
}
setInterval(() => {
  const maxAge = 10 * 60 * 1e3;
  const now = Date.now();
  let cleaned = 0;
  for (const [requestId, entry] of requestToClient.entries()) {
    if (now - entry.timestamp > maxAge) {
      requestToClient.delete(requestId);
      cleaned++;
    }
  }
  if (cleaned > 0) {
    stats.cleanedStaleRequests += cleaned;
    logger.warn(`Cleaned up ${cleaned} stale request entries (age > 10 min)`);
  }
}, 5 * 60 * 1e3);
function handleConnection(ws) {
  stats.totalConnections++;
  stats.activeConnections++;
  const clientId = `client_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
  ws.data = { clientId };
  logger.info(`New client connected: ${clientId}`);
  try {
    ws.send(JSON.stringify({
      type: "system",
      message: "Please join a channel to start communicating with Figma"
    }));
  } catch (error) {
    logger.error(`Failed to send welcome message to client ${clientId}:`, error);
    stats.errors++;
  }
}
var server = Bun.serve({
  port: 3055,
  hostname: "0.0.0.0",
  // uncomment this to allow connections in windows wsl
  // hostname: "0.0.0.0",
  fetch(req, server2) {
    const url = new URL(req.url);
    logger.debug(`Received ${req.method} request to ${url.pathname}`);
    if (req.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, Authorization"
        }
      });
    }
    if (url.pathname === "/status") {
      return new Response(JSON.stringify({
        status: "running",
        uptime: process.uptime(),
        stats,
        queue: {
          channels: Array.from(channelQueues.entries()).map(([name, state]) => ({
            channel: name,
            queueDepth: state.queue.length,
            isProcessing: state.isProcessing
          })),
          pendingRequests: requestToClient.size,
          agentCount: agentClients.size,
          pluginCount: pluginClients.size
        }
      }), {
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*"
        }
      });
    }
    try {
      const success = server2.upgrade(req, {
        headers: {
          "Access-Control-Allow-Origin": "*"
        }
      });
      if (success) {
        return;
      }
    } catch (error) {
      logger.error("Failed to upgrade WebSocket connection:", error);
      stats.errors++;
      return new Response("Failed to upgrade to WebSocket", { status: 500 });
    }
    return new Response("Claude to Figma WebSocket server running. Try connecting with a WebSocket client.", {
      headers: {
        "Content-Type": "text/plain",
        "Access-Control-Allow-Origin": "*"
      }
    });
  },
  websocket: {
    open: handleConnection,
    message(ws, message) {
      try {
        stats.messagesReceived++;
        const clientId = ws.data?.clientId || "unknown";
        logger.debug(`Received message from client ${clientId}:`, typeof message === "string" ? message : "<binary>");
        const data = JSON.parse(message);
        if (data.type === "join") {
          const channelName = data.channel;
          if (!channelName || typeof channelName !== "string") {
            logger.warn(`Client ${clientId} attempted to join without a valid channel name`);
            ws.send(JSON.stringify({
              type: "error",
              message: "Channel name is required"
            }));
            stats.messagesSent++;
            return;
          }
          const sessionId = data.sessionId;
          if (sessionId && typeof sessionId === "string") {
            const oldWs = sessionToClient.get(sessionId);
            if (oldWs && oldWs !== ws) {
              logger.info(`Session ${sessionId} reconnected (client ${clientId}). Closing stale connection.`);
              const oldChannels = [];
              channels.forEach((clients, ch) => {
                if (clients.has(oldWs)) oldChannels.push(ch);
              });
              channels.forEach((clients) => clients.delete(oldWs));
              cleanupClient(oldWs, oldChannels);
              try {
                oldWs.close(1e3, "Replaced by reconnecting session");
              } catch {
              }
              stats.activeConnections--;
            }
            sessionToClient.set(sessionId, ws);
            ws.data.sessionId = sessionId;
          }
          if (!channels.has(channelName)) {
            logger.info(`Creating new channel: ${channelName}`);
            channels.set(channelName, /* @__PURE__ */ new Set());
          }
          const channelClients = channels.get(channelName);
          channelClients.add(ws);
          logger.info(`Client ${clientId} joined channel: ${channelName}`);
          try {
            ws.send(JSON.stringify({
              type: "system",
              message: `Joined channel: ${channelName}`,
              channel: channelName
            }));
            stats.messagesSent++;
            ws.send(JSON.stringify({
              type: "system",
              message: {
                id: data.id,
                result: "Connected to channel: " + channelName
              },
              channel: channelName
            }));
            stats.messagesSent++;
            logger.debug(`Connection confirmation sent to client ${clientId} for channel ${channelName}`);
          } catch (error) {
            logger.error(`Failed to send join confirmation to client ${clientId}:`, error);
            stats.errors++;
          }
          try {
            let notificationCount = 0;
            channelClients.forEach((client) => {
              if (client !== ws && client.readyState === WebSocket.OPEN) {
                client.send(JSON.stringify({
                  type: "system",
                  message: "A new client has joined the channel",
                  channel: channelName
                }));
                stats.messagesSent++;
                notificationCount++;
              }
            });
            if (notificationCount > 0) {
              logger.debug(`Notified ${notificationCount} other clients in channel ${channelName}`);
            }
          } catch (error) {
            logger.error(`Error notifying channel about new client:`, error);
            stats.errors++;
          }
          return;
        }
        if (data.type === "message") {
          const channelName = data.channel;
          if (!channelName || typeof channelName !== "string") {
            logger.warn(`Client ${clientId} sent message without a valid channel name`);
            ws.send(JSON.stringify({
              type: "error",
              message: "Channel name is required"
            }));
            stats.messagesSent++;
            return;
          }
          const channelClients = channels.get(channelName);
          if (!channelClients || !channelClients.has(ws)) {
            logger.warn(`Client ${clientId} attempted to send to channel ${channelName} without joining first`);
            ws.send(JSON.stringify({
              type: "error",
              message: "You must join the channel first"
            }));
            stats.messagesSent++;
            return;
          }
          classifyClient(ws, data);
          const isCommand = !!data.message?.command;
          const isResponse = data.message?.result !== void 0 || data.message?.error !== void 0;
          if (isResponse) {
            handleResponseFromPlugin(data, channelName);
            return;
          }
          if (isCommand) {
            const validationError = validateCommand(data, channelName);
            if (validationError) {
              ws.send(JSON.stringify({
                type: "broadcast",
                message: { id: data.message.id, error: validationError },
                sender: "You",
                channel: channelName
              }));
              stats.blockedCommands++;
              stats.messagesSent++;
              return;
            }
            enqueueCommand(data, ws, channelName);
            return;
          }
          try {
            let broadcastCount = 0;
            channelClients.forEach((client) => {
              if (client.readyState === WebSocket.OPEN) {
                client.send(JSON.stringify({
                  type: "broadcast",
                  message: data.message,
                  sender: client === ws ? "You" : "User",
                  channel: channelName
                }));
                stats.messagesSent++;
                broadcastCount++;
              }
            });
            logger.debug(`Broadcasted non-command message to ${broadcastCount} clients in channel ${channelName}`);
          } catch (error) {
            logger.error(`Error broadcasting message to channel ${channelName}:`, error);
            stats.errors++;
          }
        }
        if (data.type === "progress_update") {
          const channelName = data.channel;
          if (!channelName || typeof channelName !== "string") {
            logger.warn(`Client ${clientId} sent progress update without a valid channel name`);
            return;
          }
          const channelClients = channels.get(channelName);
          if (!channelClients) {
            logger.warn(`Progress update for non-existent channel: ${channelName}`);
            return;
          }
          logger.debug(`Progress update for command ${data.id} in channel ${channelName}: ${data.message?.data?.status || "unknown"} - ${data.message?.data?.progress || 0}%`);
          const requestId = data.id;
          const entry = requestId ? requestToClient.get(requestId) : null;
          if (entry && entry.ws.readyState === WebSocket.OPEN) {
            try {
              entry.ws.send(JSON.stringify(data));
              stats.messagesSent++;
            } catch (error) {
              logger.error(`Failed to unicast progress update:`, error);
            }
          } else {
            try {
              channelClients.forEach((client) => {
                if (client.readyState === WebSocket.OPEN) {
                  client.send(JSON.stringify(data));
                  stats.messagesSent++;
                }
              });
            } catch (error) {
              logger.error(`Error broadcasting progress update:`, error);
              stats.errors++;
            }
          }
        }
      } catch (err) {
        stats.errors++;
        logger.error("Error handling message:", err);
        try {
          ws.send(JSON.stringify({
            type: "error",
            message: "Error processing your message: " + (err instanceof Error ? err.message : String(err))
          }));
          stats.messagesSent++;
        } catch (sendError) {
          logger.error("Failed to send error message to client:", sendError);
        }
      }
    },
    close(ws, code, reason) {
      const clientId = ws.data?.clientId || "unknown";
      logger.info(`WebSocket closed for client ${clientId}: Code ${code}, Reason: ${reason || "No reason provided"}`);
      const clientChannels = [];
      channels.forEach((clients, channelName) => {
        if (clients.has(ws)) clientChannels.push(channelName);
      });
      channels.forEach((clients, channelName) => {
        if (clients.delete(ws)) {
          logger.debug(`Removed client ${clientId} from channel ${channelName} due to connection close`);
          try {
            clients.forEach((client) => {
              if (client.readyState === WebSocket.OPEN) {
                client.send(JSON.stringify({
                  type: "system",
                  message: "A client has left the channel",
                  channel: channelName
                }));
                stats.messagesSent++;
              }
            });
          } catch (error) {
            logger.error(`Error notifying channel ${channelName} about client disconnect:`, error);
            stats.errors++;
          }
          if (clients.size === 0) {
            channels.delete(channelName);
            channelQueues.delete(channelName);
            logger.debug(`Cleaned up empty channel: ${channelName}`);
          }
        }
      });
      cleanupClient(ws, clientChannels);
      if (ws.data?.sessionId) {
        const currentHolder = sessionToClient.get(ws.data.sessionId);
        if (currentHolder === ws) {
          sessionToClient.delete(ws.data.sessionId);
        }
      }
      stats.activeConnections--;
    },
    drain(ws) {
      const clientId = ws.data?.clientId || "unknown";
      logger.debug(`WebSocket backpressure relieved for client ${clientId}`);
    }
  }
});
logger.info(`Claude to Figma WebSocket server running on port ${server.port}`);
logger.info(`Status endpoint available at http://localhost:${server.port}/status`);
setInterval(() => {
  logger.info("Server stats:", {
    channels: channels.size,
    ...stats,
    queueState: Array.from(channelQueues.entries()).map(([name, state]) => ({
      channel: name,
      depth: state.queue.length,
      processing: state.isProcessing
    }))
  });
}, 5 * 60 * 1e3);
//# sourceMappingURL=socket.js.map