import { useEffect, useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';

import { readTaskRecipes, reviewTaskRecipe, RECIPE_EVENT, type TaskRecipe } from './taskRecipes';

export function SavedTaskRecipes({ onUse }: { onUse: (recipe: TaskRecipe) => void }) {
  const { locale } = useI18n();
  const en = locale === 'en';
  const [recipes, setRecipes] = useState<TaskRecipe[]>([]);
  const [error, setError] = useState(false);
  const load = () => {
    try {
      setRecipes(readTaskRecipes());
      setError(false);
    } catch {
      setError(true);
    }
  };
  useEffect(() => {
    load();
    window.addEventListener(RECIPE_EVENT, load);
    return () => window.removeEventListener(RECIPE_EVENT, load);
  }, []);
  if (!recipes.length && !error) return null;
  return (
    <section
      className="w-full max-w-2xl rounded border border-ui-border p-3"
      data-testid="saved-task-recipes"
    >
      <h2 className="text-ui-base font-semibold">
        {en ? 'Reusable task recipes' : '可复用任务配方'}
      </h2>
      <p className="text-ui-sm text-text-secondary mt-1">
        {en
          ? 'Saved definitions do not run automatically. User review is separate from automated validation.'
          : '保存不等于执行；用户核对不等于系统自动校验。运行前仍会确认参数、项目和权限。'}
      </p>
      {error && (
        <p role="alert" className="text-ui-sm text-error">
          {en
            ? 'Recipes could not be read or updated; existing data has not been overwritten.'
            : '配方读取或更新失败，未覆盖已有数据。'}
        </p>
      )}
      {recipes.map((recipe) => (
        <div
          key={recipe.id}
          className="flex flex-wrap items-center gap-2 py-2 border-b border-ui-border"
        >
          <span className="flex-1 min-w-0 text-ui-base truncate">{recipe.name}</span>
          <span className="text-ui-sm text-text-secondary">
            {recipe.reviewedAt
              ? en
                ? 'Reviewed by user'
                : '用户已核对'
              : en
                ? 'Draft · not reviewed'
                : '草稿 · 未验收'}
          </span>
          {!recipe.reviewedAt && (
            <button
              type="button"
              className="text-ui-sm underline"
              onClick={() => {
                if (
                  window.confirm(
                    en
                      ? 'Have you reviewed the deliverable and its sources? This records only your manual review.'
                      : '是否已检查交付物和来源？此操作只记录你的人工核对，不冒充自动验真。',
                  )
                ) {
                  try {
                    reviewTaskRecipe(recipe.id);
                  } catch {
                    setError(true);
                  }
                }
              }}
            >
              {en ? 'Record my review' : '记录人工核对'}
            </button>
          )}
          <button
            type="button"
            className="text-ui-sm px-2 py-1 rounded border border-ui-border"
            onClick={() => onUse(recipe)}
          >
            {en ? 'Review inputs and reuse' : '确认参数后复用'}
          </button>
        </div>
      ))}
    </section>
  );
}
