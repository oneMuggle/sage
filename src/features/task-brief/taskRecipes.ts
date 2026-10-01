import { taskBriefPrompt, type TaskBrief } from './taskBrief';

const KEY = 'sage:task-recipes:v1';
export const RECIPE_EVENT = 'sage:task-recipes-changed';
export interface TaskRecipe {
  id: string;
  name: string;
  brief: TaskBrief;
  createdAt: number;
  reviewedAt: number | null;
}

export function readTaskRecipes(): TaskRecipe[] {
  const raw = localStorage.getItem(KEY);
  if (raw === null) return [];
  const data: unknown = JSON.parse(raw);
  if (
    !data ||
    typeof data !== 'object' ||
    !('version' in data) ||
    data.version !== 1 ||
    !('recipes' in data) ||
    !Array.isArray(data.recipes) ||
    data.recipes.length > 64
  )
    throw new Error('Unsupported recipe store');
  return data.recipes.map((item: TaskRecipe) => {
    if (
      !item ||
      typeof item.id !== 'string' ||
      typeof item.name !== 'string' ||
      item.name.length > 120 ||
      !Number.isFinite(item.createdAt) ||
      !(item.reviewedAt === null || Number.isFinite(item.reviewedAt))
    )
      throw new Error('Invalid recipe');
    taskBriefPrompt(item.brief);
    return item;
  });
}
function persist(recipes: TaskRecipe[]): void {
  localStorage.setItem(KEY, JSON.stringify({ version: 1, recipes }));
  window.dispatchEvent(new Event(RECIPE_EVENT));
}
export function saveTaskRecipe(brief: TaskBrief): TaskRecipe {
  taskBriefPrompt(brief);
  const current = readTaskRecipes(); // Never overwrite a corrupt or unreadable store.
  if (current.length >= 64) throw new Error('Recipe limit reached');
  const recipe: TaskRecipe = {
    id: crypto.randomUUID(),
    name: brief.goal.trim().slice(0, 120),
    brief: { ...brief },
    createdAt: Date.now(),
    reviewedAt: null,
  };
  persist([recipe, ...current]);
  return recipe;
}
/** Explicit user review, not a claim of automatic/backend verification. */
export function reviewTaskRecipe(id: string): void {
  const recipes = readTaskRecipes();
  if (!recipes.some((recipe) => recipe.id === id)) throw new Error('Recipe does not exist');
  persist(
    recipes.map((recipe) => (recipe.id === id ? { ...recipe, reviewedAt: Date.now() } : recipe)),
  );
}
