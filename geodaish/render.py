"""Optional pygame window and RGB frames, independent of training speed."""

import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import numpy as np
import pygame


class Renderer:
    width, height = 1100, 620
    scale, ground = 68, 460

    def __init__(self, mode):
        self.mode = mode
        pygame.font.init()
        self.screen = None
        if mode == "human":
            pygame.display.init()
            self.screen = pygame.display.set_mode((self.width, self.height))
            pygame.display.set_caption("GEODAISH / Reinforcement learning lab")
        self.surface = pygame.Surface((self.width, self.height))
        self.font = pygame.font.Font(None, 25)
        self.small = pygame.font.Font(None, 20)
        self.large = pygame.font.Font(None, 44)
        self.clock = pygame.time.Clock()

    def text(self, text, pos, color=(180, 194, 215), large=False):
        self.surface.blit((self.large if large else self.font).render(text, True, color), pos)

    def draw(self, env):
        s = self.surface
        s.fill((10, 15, 28))
        offset = env.x * self.scale
        for x in range(-80, self.width + 80, 68):
            px = x - int(offset * 0.35) % 68
            pygame.draw.line(s, (20, 29, 46), (px, 150), (px, self.ground))
        for y in range(188, self.ground, 68):
            pygame.draw.line(s, (20, 29, 46), (0, y), (self.width, y))
        pygame.draw.rect(s, (17, 28, 42), (0, self.ground, self.width, 160))
        pygame.draw.line(s, (92, 230, 185), (0, self.ground), (self.width, self.ground), 2)
        self.text("GEODAISH", (34, 26), (240, 245, 252), large=True)
        self.text("REINFORCEMENT LEARNING LAB", (36, 75))
        self.text(f"{env.difficulty.upper()}  /  {env.passed:02d} OF {env.group_count:02d} CLEARED", (688, 40))
        progress = min(env.x / env.level_length, 1)
        pygame.draw.rect(s, (33, 45, 62), (36, 117, 1028, 5), border_radius=2)
        pygame.draw.rect(s, (92, 230, 185), (36, 117, int(1028 * progress), 5), border_radius=2)
        player_x = 190
        for obstacle in env.obstacles:
            for i in range(obstacle.count):
                left = player_x + (obstacle.x + i * 0.7 - env.x) * self.scale
                if not -60 < left < self.width + 20:
                    continue
                points = [(left, self.ground), (left + 0.35 * self.scale,
                          self.ground - obstacle.height * self.scale),
                          (left + 0.7 * self.scale, self.ground)]
                pygame.draw.polygon(s, (108, 43, 68), points)
                pygame.draw.polygon(s, (255, 112, 146), points, 3)
        finish_x = int(player_x + (env.level_length - env.x) * self.scale)
        if 0 < finish_x < self.width:
            pygame.draw.line(s, (92, 230, 185), (finish_x, 205), (finish_x, self.ground), 3)
            self.text("FINISH", (finish_x - 35, 175), (92, 230, 185))
        size = int(env.player_size * self.scale)
        top = int(self.ground - (env.y + env.player_size) * self.scale)
        color = (255, 112, 146) if env.dead else (92, 230, 185)
        pygame.draw.rect(s, color, (player_x, top, size, size), border_radius=5)
        pygame.draw.rect(s, (10, 30, 32), (player_x + 9, top + 9, size - 18, size - 18), 3)
        for eye in (17, 35):
            pygame.draw.rect(s, (10, 30, 32), (player_x + eye, top + 18, 5, 8))
        self.text("PROGRESS", (36, 503))
        self.text(f"{progress:.0%}", (36, 539), (240, 245, 252), large=True)
        self.text("JUMPS", (230, 503))
        self.text(str(env.jumps), (230, 539), (240, 245, 252), large=True)
        self.text("SPACE / HOLD TO JUMP     R / RESTART     ESC / EXIT", (485, 552))
        if env._done:
            label = "LEVEL COMPLETE" if env.success else "TRY AGAIN" if env.dead else "TIME LIMIT"
            self.text(label, (400, 240), color, large=True)
            self.text("Press R to restart", (444, 290))
        if self.screen is not None:
            self.screen.blit(s, (0, 0))
            pygame.display.flip()
            self.clock.tick(60)
            pygame.event.pump()
            if pygame.event.peek(pygame.QUIT):
                env.closed = True
            return None
        return np.transpose(pygame.surfarray.array3d(s), (1, 0, 2))

    def close(self):
        if self.screen is not None:
            pygame.display.quit()
