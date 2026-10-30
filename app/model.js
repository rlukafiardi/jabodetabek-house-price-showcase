// Browser predictor for the exported model (src/modeling/export.py): mean of XGBoost and ridge, both on the model's features plus a
// text score from a TF-IDF ridge, predicting log price per m² of land. All arithmetic mirrors scikit-learn and XGBoost.

const WORD = /[a-z]{3,}/g; // the training text keeps letters-only words of 3+ characters (src/ingestion/parse.py: clean_words)

export function cleanWords(text) {
  return (text.toLowerCase().replace(/\S+@\S+|https?:\/\/\S+|www\.\S+/g, " ").match(WORD) || []);
}

export function textScore(text, words) {
  const tokens = cleanWords(words);
  const counts = new Map();
  const add = (term) => { if (text.vocabulary[term]) counts.set(term, (counts.get(term) || 0) + 1); };
  tokens.forEach((t, i) => { add(t); if (i + 1 < tokens.length) add(`${t} ${tokens[i + 1]}`); });
  let norm = 0;
  const weights = [];
  for (const [term, count] of counts) {
    const [index, idf] = text.vocabulary[term];
    const weight = (1 + Math.log(count)) * idf; // sublinear tf times idf
    weights.push([index, weight]);
    norm += weight * weight;
  }
  norm = Math.sqrt(norm) || 1;
  return weights.reduce((sum, [index, weight]) => sum + text.coef[index] * (weight / norm), text.intercept);
}

function treeValue(tree, x) {
  let node = 0;
  while (tree.feature[node] !== -1) {
    const v = x[tree.feature[node]];
    node = Number.isNaN(v) ? tree.missing[node] : (Math.fround(v) < Math.fround(tree.value[node]) ? tree.yes[node] : tree.no[node]);
  }
  return tree.value[node];
}

function xgboost(model, x) {
  return model.trees.reduce((sum, tree) => sum + treeValue(tree, x), model.base_score);
}

function ridge(model, x) {
  const filled = x.map((v, j) => (Number.isNaN(v) ? model.medians[j] : v));
  const indicators = model.indicator_features.map((j) => (Number.isNaN(x[j]) ? 1 : 0));
  const row = [...filled, ...indicators];
  return row.reduce((sum, v, j) => sum + model.coef[j] * ((v - model.mean[j]) / model.scale[j]), model.intercept);
}

/** The three parts separately (for the parity test). */
export function parts(model, features, words = "") {
  const score = textScore(model.text, words);
  const withText = { ...features, text_score: score };
  const x = model.features.map((name) => (withText[name] === null || withText[name] === undefined ? NaN : Number(withText[name])));
  return { xgboost: xgboost(model.xgboost, x), ridge: ridge(model.ridge, x), text_score: score };
}

/** features: object keyed by feature name (null or undefined = missing); words: the free-text notes. Returns log price per m² of land. */
export function predictLogPpm2(model, features, words = "") {
  const withText = { ...features, text_score: textScore(model.text, words) };
  const x = model.features.map((name) => (withText[name] === null || withText[name] === undefined ? NaN : Number(withText[name])));
  return (xgboost(model.xgboost, x) + ridge(model.ridge, x)) / 2;
}
