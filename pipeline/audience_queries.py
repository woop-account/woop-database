"""SQL builders for the WOOP Audience Explorer refresh (Metabase database 67, MySQL).
Rules used (agreed so far):
  consented mom = has an opt-in row for a WOOP organisation
  unique mom    = earliest consented lead per UniqueIdentifier (provisional key)
  data points   = number of non-blank answer fields on the lead (no names, emails, phones, addresses)
"""
BQ = ("India_PampersPremiumCare_Features Indo_AbbottPediasure_UsageStaus PH_JJMilkRiceBathLotion_Preference PH_JJMilkRiceBathLotion_BabySkin PH_JJMilkRiceBathLotion_BestSkincareRegimen Agegroup_YoungestChild IND_PET IND_Beauty_Concerns IND_Family_HealthConcerns IND_City IND_PregnancyPackage_Budget IND_Caregiver Ind_Diaper_Size Ind_MoreThan65kDeliveryExpense INDO_OralHealthProblem INDO_Hijab INDO_SocialMedia Monthly_Income Dog_FoodBrand Dog_Size Dog_Age Zwitsal_AloeveraLotion Zwitsal_HairLotion Caregiver DateToJoin_Kulwhap_Webinars VaselineM_BodycareFormat VaselineM_BodycareAdvantages UL_OPTIN_EML UL_OPTIN_SMS PH_Trimester LifeCell_Occupation CreditCard CharityNGO UnderarmIssue DeoRoll Allergy SkinCare UL_CompetitorBrands UL_SnackPreference UL_RecipesSearch UL_CookingFor mom_community addcol1 cat_breed cat_age first_time_pet Sanitary_Pad BirthYear toothpaste gender product_buy product_categeory new_mom body_lotion freq_purchasing money_spent education cat_food pet_concern brand_premium hair_care hair_concern hair_brand deo_brand body_concern deo_format ethnicity dove1 dove2 lifebouy1 lifebuoy2 addcol2 FoodbrandPreference MilkInsights PregnancyInsights MaternalMilkInsights addcol3 LaundryInsights EngagementInsights".split()
      + [f"addcol{i}" for i in range(4, 28)])
CO = ["MomDOB","MomAge","DueDate","ChildDOB","AdditionalChildDOB","SecondChildDOB","ChildGender","OnlinePurchases","OwnedAppliances","PreferredFormulaMilkBrand","PreferredDiapersBrand","PreferredMaternalMilkBrand","MomsInterests","Occupation","PreferredBabySkinCareBrand","BreastpumpInsights","MotherhoodChallangesInsights","HealthConcerns","BrandsYouUse","HouseholdIncome","WOOPSegment","ENFASegment","ChildHeight","ChildWeight","ChildShowcaseSign","AnybodyType2Diabetes","Type2DiabetesSupplements","UrinaryIncontinence","PickyEater"]
DATE_COLS = {"MomDOB", "DueDate", "ChildDOB", "AdditionalChildDOB", "SecondChildDOB"}
ORG = "('WOOP INDIA','WOOP PH','WOOP INDO','WOOP MY','WOOP TH','WOOP Vietnam','WOOP Singapore')"

def ans(t, col):
    """1 if the answer has any visible character (blank, spaces and newline-only answers count as empty)."""
    return f"({t}.{col} IS NOT NULL)" if col in DATE_COLS else f"COALESCE({t}.{col} REGEXP '[^[:space:]]', 0)"

DP = " + ".join([ans("c", x) for x in CO] + [ans("b", x) for x in BQ])
FROM_WHERE = lambda a, b, before: f""" FROM SURVEY_ANYPLACE_LEADS l
 LEFT JOIN SURVEY_ANYPLACE_COMPUTATION c ON c.LeadId = l.id
 LEFT JOIN SURVEY_ANYPLACE_BrandQ b ON b.LeadId = l.id
 WHERE l.id BETWEEN {a} AND {b}{f" AND l.CreatedDate < '{before}'" if before else ""}
  AND EXISTS (SELECT 1 FROM OPT_IN_SA_LEADS o WHERE o.LeadId = l.id AND o.Organisation IN {ORG})"""
CANON = f"(NULLIF(TRIM(l.UniqueIdentifier),'') IS NULL OR NOT EXISTS (SELECT 1 FROM SURVEY_ANYPLACE_LEADS l2 WHERE l2.UniqueIdentifier = l.UniqueIdentifier AND l2.id < l.id AND EXISTS (SELECT 1 FROM OPT_IN_SA_LEADS o2 WHERE o2.LeadId = l2.id AND o2.Organisation IN {ORG})))"
COUNTRY = ("CASE WHEN LOWER(TRIM(x.Country)) = 'india' THEN 'India' WHEN LOWER(TRIM(x.Country)) = 'indonesia' THEN 'Indonesia' "
           "WHEN LOWER(TRIM(x.Country)) = 'malaysia' THEN 'Malaysia' WHEN LOWER(TRIM(x.Country)) = 'philippines' THEN 'Philippines' ELSE 'Other ASEAN' END")   # fixed labels: 'INDIA' and 'India' must land in one group

def q1(a, b, before=None):
    """Query 1: totals per country. before='2026-03-01' counts only leads created before that date."""
    return f"""SELECT {COUNTRY} AS country,
 COUNT(*) AS consented_leads, SUM(x.canon) AS unique_moms, SUM(x.dp) AS data_points
FROM (
 SELECT l.id, l.Country, {CANON} AS canon, {DP} AS dp
{FROM_WHERE(a, b, before)}
) x GROUP BY 1 ORDER BY 2 DESC"""

# --- Query 2: macro audiences ---------------------------------------------------------------
NO_CHILD = ("don.t have|do not have|tidak punya anak|tidak mempunyai anak|tidak ada anak|không có con|"
           "\u0e44\u0e21\u0e48\u0e21\u0e35\u0e25\u0e39\u0e01|"                      # Thai: no child
           "\u0b95\u0bc1\u0bb4\u0ba8\u0bcd\u0ba4\u0bc8\u0b95\u0bb3\u0bcd \u0b87\u0bb2\u0bcd\u0bb2\u0bc8|"   # Tamil: no children
           "\u0c2a\u0c3f\u0c32\u0c4d\u0c32\u0c32\u0c41 \u0c32\u0c47\u0c30\u0c41")            # Telugu: no children
DOGCAT = ("dog|cat|anjing|kucing|chó|mèo|"
          "\u0ba8\u0bbe\u0baf\u0bcd|\u0baa\u0bc2\u0ba9\u0bc8|"                      # Tamil: dog, cat
          "\u0c15\u0c41\u0c15\u0c4d\u0c15|\u0c2a\u0c3f\u0c32\u0c4d\u0c32\u0c3f|"        # Telugu: dog, cat
          "\u0e2a\u0e38\u0e19\u0e31\u0e02|\u0e41\u0e21\u0e27")                    # Thai: dog, cat
def q2(a, b, before=None):
    """Query 2: moms and data points per country for Kids, Pets and the 45-plus part of Senior & health.
    Women = all moms (use Query 1). The caregiver part of Senior & health needs a definition from the data team."""
    flags = f"""
  IFNULL(c.ChildDOB >= '1990-01-01' AND c.ChildDOB <= NOW(), 0) AS k_dob,
  IFNULL(c.DueDate >= '2015-01-01', 0) AS k_due,
  IFNULL(b.Agegroup_YoungestChild REGEXP '[^[:space:]]' AND NOT (b.Agegroup_YoungestChild REGEXP '{NO_CHILD}'), 0) AS k_age,
  IFNULL(b.IND_PET REGEXP '{DOGCAT}', 0) AS p_ind,
  ({ans('b','Dog_Age')} + {ans('b','Dog_Size')} + {ans('b','Dog_FoodBrand')} + {ans('b','cat_age')} + {ans('b','cat_breed')} + {ans('b','cat_food')} > 0) AS p_other,
  IFNULL(LOWER(TRIM(b.Caregiver)) IN ('yes','ya','có'), 0) AS cg,
  IFNULL((c.MomDOB > '1940-12-31' AND c.MomDOB <= DATE_SUB(CURDATE(), INTERVAL 45 YEAR)) OR (c.MomAge REGEXP '^(above|diatas|lebih|46|5[0-9])'), 0) AS age45"""
    return f"""SELECT {COUNTRY} AS country,
 SUM(x.canon) AS unique_moms,
 SUM(x.canon * (x.k_dob OR x.k_due OR x.k_age)) AS kids_moms, SUM((x.k_dob OR x.k_due OR x.k_age) * x.dp) AS kids_dp,
 SUM(x.canon * (x.p_ind OR x.p_other)) AS pets_moms, SUM((x.p_ind OR x.p_other) * x.dp) AS pets_dp,
 SUM(x.canon * x.age45) AS seniors_45_plus_moms, SUM(x.age45 * x.dp) AS seniors_45_plus_dp,
 SUM(x.canon * x.k_dob) AS chk_kids_by_child_dob, SUM(x.canon * x.k_age * (1 - x.k_dob) * (1 - x.k_due)) AS chk_kids_by_agegroup_only,
 SUM(x.canon * x.p_ind) AS chk_pets_by_pet_answer, SUM(x.canon * x.cg) AS chk_caregiver_yes, SUM(x.canon * x.age45) AS chk_age_45_plus
FROM (
 SELECT l.id, l.Country, {CANON} AS canon, {DP} AS dp,{flags}
{FROM_WHERE(a, b, before)}
) x GROUP BY 1 ORDER BY 2 DESC"""

# --- Query 3: micro audiences ----------------------------------------------------------------
# Answers that mean "under 1 year" for a pet (6 months and below / 7-12 months), in the languages seen so far.
PET_UNDER_1 = ("month|bulan|tháng|"
               "மாதங்கள்|"      # Tamil: months
               "నెలలు|"                         # Telugu: months
               "เดือน")                         # Thai: months
FIRST_TIME_YES = "('yes','ya','phải','ஆம்','అవును','ใช่')"
DOG_WORDS = "dog|anjing|chó|நாய்|కుక్క|สุนัข"
CAT_WORDS = "cat|kucing|mèo|பூனை|పిల్లి|แมว"
PREGNANT_WORDS = "pregnan|hamil|mengandung|expecting|buntis|mang thai|ตั้งครรภ์"
KIDS_ANY = "(x.k_dob OR x.k_due OR x.k_age)"
# (macro, micro name on the page, key, condition on the inner columns). Caregiver micros are left out: no definition yet.
MICROS = [
 ("Kids", "All kids", "kids_all", KIDS_ANY),
 ("Kids", "Expecting (pregnant)", "kids_expecting", "x.expecting"),
 ("Kids", "Child 0 to 6 months", "kids_0_6m", "x.k_mon >= 0 AND x.k_mon < 6"),
 ("Kids", "Child 6 to 12 months", "kids_6_12m", "x.k_mon >= 6 AND x.k_mon < 12"),
 ("Kids", "Child 1 to 2 years", "kids_1_2y", "x.k_mon >= 12 AND x.k_mon < 24"),
 ("Kids", "Child 2 to 3 years", "kids_2_3y", "x.k_mon >= 24 AND x.k_mon < 36"),
 ("Kids", "Child 3 to 5 years", "kids_3_5y", "x.k_mon >= 36 AND x.k_mon < 60"),
 ("Kids", "Child 5 to 8 years", "kids_5_8y", "x.k_mon >= 60 AND x.k_mon < 96"),
 ("Kids", "Child 8 to 10 years", "kids_8_10y", "x.k_mon >= 96 AND x.k_mon < 120"),
 ("Kids", "Child 10 to 15 years", "kids_10_15y", "x.k_mon >= 120 AND x.k_mon < 180"),
 ("Kids", "Child above 15 years", "kids_15y_plus", "x.k_mon >= 180"),
 ("Pets", "All pet parents", "pets_all", "(x.p_ind OR x.p_other)"),
 ("Pets", "Dog under 1 year", "dog_u1", "x.dog_age_ans AND x.dog_u1"),
 ("Pets", "Dog 1 year and over", "dog_1p", "x.dog_age_ans AND NOT x.dog_u1"),
 ("Pets", "Cat under 1 year", "cat_u1", "x.cat_age_ans AND x.cat_u1"),
 ("Pets", "Cat 1 year and over", "cat_1p", "x.cat_age_ans AND NOT x.cat_u1"),
 ("Pets", "First-time pet parents", "pets_first", "(x.p_ind OR x.p_other) AND x.ftp"),
 ("Senior & health", "Seniors (mom aged 45 or above)", "seniors_45", "x.age_band = 'a45'"),
 ("Women", "All women", "women_all", "1"),
 ("Women", "Aged 18 to 25", "women_18_25", "x.age_band = 'a1825'"),
 ("Women", "Aged 25 to 45", "women_25_45", "x.age_band = 'a2545'"),
 ("Women", "Aged 45 or above", "women_45_plus", "x.age_band = 'a45'"),
]

def q3(a, b, before=None):
    """Query 3: moms and data points per country for each micro audience (wide: m_<key> = moms, d_<key> = data points)."""
    inner = f"""
  IFNULL(c.ChildDOB >= '1990-01-01' AND c.ChildDOB <= NOW(), 0) AS k_dob,
  IFNULL(c.DueDate >= '2015-01-01', 0) AS k_due,
  IFNULL(b.Agegroup_YoungestChild REGEXP '[^[:space:]]' AND NOT (b.Agegroup_YoungestChild REGEXP '{NO_CHILD}'), 0) AS k_age,
  CASE WHEN c.ChildDOB >= '1990-01-01' AND c.ChildDOB <= NOW() THEN TIMESTAMPDIFF(MONTH, c.ChildDOB, NOW()) END AS k_mon,
  IFNULL(c.DueDate >= CURDATE(), 0) AS expecting,
  IFNULL(b.Agegroup_YoungestChild REGEXP '{PREGNANT_WORDS}', 0) AS preg_text,
  IFNULL(b.IND_PET REGEXP '{DOGCAT}', 0) AS p_ind,
  ({ans('b','Dog_Age')} + {ans('b','Dog_Size')} + {ans('b','Dog_FoodBrand')} + {ans('b','cat_age')} + {ans('b','cat_breed')} + {ans('b','cat_food')} > 0) AS p_other,
  {ans('b','Dog_Age')} AS dog_age_ans, IFNULL(b.Dog_Age REGEXP '{PET_UNDER_1}', 0) AS dog_u1,
  {ans('b','cat_age')} AS cat_age_ans, IFNULL(b.cat_age REGEXP '{PET_UNDER_1}', 0) AS cat_u1,
  IFNULL(LOWER(TRIM(b.first_time_pet)) IN {FIRST_TIME_YES}, 0) AS ftp,
  CASE WHEN c.MomDOB > '1940-12-31' AND c.MomDOB <= DATE_SUB(CURDATE(), INTERVAL 13 YEAR) THEN
         CASE WHEN c.MomDOB > DATE_SUB(CURDATE(), INTERVAL 18 YEAR) THEN 'u18' WHEN c.MomDOB > DATE_SUB(CURDATE(), INTERVAL 25 YEAR) THEN 'a1825'
              WHEN c.MomDOB > DATE_SUB(CURDATE(), INTERVAL 45 YEAR) THEN 'a2545' ELSE 'a45' END
       WHEN c.MomAge REGEXP '^(18|19|20|21|22|23|24)' THEN 'a1825'
       WHEN c.MomAge REGEXP '^(2[5-9]|3[0-9]|4[0-5])' THEN 'a2545'
       WHEN c.MomAge REGEXP '^(above|diatas|lebih|4[6-9]|5[0-9])' THEN 'a45' END AS age_band"""
    sums = ",\n ".join(f"SUM(x.canon * IFNULL(({cond}), 0)) AS m_{k}, SUM(IFNULL(({cond}), 0) * x.dp) AS d_{k}" for _, _, k, cond in MICROS)
    chk = "SUM(x.canon * x.preg_text) AS chk_pregnant_by_answer, SUM(x.canon * (x.k_dob OR x.k_due OR x.k_age) * (1 - IFNULL(x.k_mon IS NOT NULL, 0))) AS chk_kids_without_child_dob"
    return f"""SELECT {COUNTRY} AS country,
 {sums},
 {chk}
FROM (
 SELECT l.id, l.Country, {CANON} AS canon, {DP} AS dp,{inner}
{FROM_WHERE(a, b, before)}
) x GROUP BY 1 ORDER BY 1"""

def micros_to_rows(res):
    """Turn the wide Query 3 result (one row per country) into rows for audience_tracker.upsert_db."""
    out = []
    for _, r in res.iterrows():
        for macro, micro, k, _ in MICROS:
            out += [dict(tab="micro", country=r["country"], macro=macro, micro=micro, metric="moms_on_file", value=int(r[f"m_{k}"])),
                    dict(tab="micro", country=r["country"], macro=macro, micro=micro, metric="data_points", value=int(r[f"d_{k}"]))]
    return out


# --- Query 5: Pets nano audiences ------------------------------------------------------------
# The page counts each nano INSIDE a micro audience (e.g. "Dog food brand known" among "Dog 1 year and over").
# (micro, group, nano) combinations exactly as on the page. The two tag nanos (Verified pet owner, Verified affluence) are skipped: no column.
PETS_COMBOS = [
    ('All pet parents', 'Pet type', 'Dog parent'),
    ('All pet parents', 'Pet type', 'Cat parent'),
    ('All pet parents', 'Pet type', 'First-time dog parent'),
    ('All pet parents', 'Pet type', 'First-time cat parent'),
    ('All pet parents', 'Pet age', 'Dog under 1 year'),
    ('All pet parents', 'Pet age', 'Dog 1 year and over'),
    ('All pet parents', 'Pet age', 'Cat under 1 year'),
    ('All pet parents', 'Pet age', 'Cat 1 year and over'),
    ('Dog under 1 year', 'Dog details', 'Dog food brand known'),
    ('Dog under 1 year', 'Dog details', 'Dog size known'),
    ('Dog under 1 year', 'Pet health', 'Pet health concerns'),
    ('Dog 1 year and over', 'Dog details', 'Dog food brand known'),
    ('Dog 1 year and over', 'Dog details', 'Dog size known'),
    ('Dog 1 year and over', 'Pet health', 'Pet health concerns'),
    ('Cat under 1 year', 'Cat details', 'Cat food brand known'),
    ('Cat under 1 year', 'Pet health', 'Pet health concerns'),
    ('Cat 1 year and over', 'Cat details', 'Cat food brand known'),
    ('Cat 1 year and over', 'Pet health', 'Pet health concerns'),
    ('First-time pet parents', 'Pet type', 'Dog parent'),
    ('First-time pet parents', 'Pet type', 'Cat parent'),
    ('First-time pet parents', 'Pet health', 'Pet health concerns'),
    ('All pet parents', 'Pet health', 'Pet health concerns'),
    ('All pet parents', 'About mom', 'Aged 25 to 45'),
    ('All pet parents', 'About mom', 'Working moms'),
    ('All pet parents', 'About mom', 'Home-maker'),
    ('All pet parents', 'Affluence', 'Uses a credit card'),
    ('Dog under 1 year', 'About mom', 'Aged 25 to 45'),
    ('Dog under 1 year', 'About mom', 'Working moms'),
    ('Dog under 1 year', 'About mom', 'Home-maker'),
    ('Dog under 1 year', 'Affluence', 'Uses a credit card'),
    ('Dog 1 year and over', 'About mom', 'Aged 25 to 45'),
    ('Dog 1 year and over', 'About mom', 'Working moms'),
    ('Dog 1 year and over', 'About mom', 'Home-maker'),
    ('Dog 1 year and over', 'Affluence', 'Uses a credit card'),
    ('Cat under 1 year', 'About mom', 'Aged 25 to 45'),
    ('Cat under 1 year', 'About mom', 'Working moms'),
    ('Cat under 1 year', 'About mom', 'Home-maker'),
    ('Cat under 1 year', 'Affluence', 'Uses a credit card'),
    ('Cat 1 year and over', 'About mom', 'Aged 25 to 45'),
    ('Cat 1 year and over', 'About mom', 'Working moms'),
    ('Cat 1 year and over', 'About mom', 'Home-maker'),
    ('Cat 1 year and over', 'Affluence', 'Uses a credit card'),
    ('First-time pet parents', 'About mom', 'Aged 25 to 45'),
    ('First-time pet parents', 'About mom', 'Working moms'),
    ('First-time pet parents', 'About mom', 'Home-maker'),
    ('First-time pet parents', 'Affluence', 'Uses a credit card'),
]
OCC_HOME = ("home.?maker|ibu rumah tangga|housewife|pembuat rumah|"
            "\u0e41\u0e21\u0e48\u0e1a\u0e49\u0e32\u0e19")                           # Thai: home-maker
OCC_WORK = ("profession|freelanc|pekerja|bekerja|entrepren|wiraswasta|usahawan|blogger|influencer|salaried|self.employed|business|teacher|government|healthcare|"
            "chuy\u00ean vi\u00ean|l\u00e0m t\u1ef1 do|doanh nh\u00e2n|"                 # Vietnamese: professional, freelance, entrepreneur
            "\u0e17\u0e33\u0e07\u0e32\u0e19|\u0e1c\u0e39\u0e49\u0e1b\u0e23\u0e30\u0e01\u0e2d\u0e1a\u0e01\u0e32\u0e23|"   # Thai: works, entrepreneur
            "\u0e1a\u0e25\u0e47\u0e2d\u0e01\u0e40\u0e01\u0e2d\u0e23\u0e4c")                # Thai: blogger
CARD_YES = "^(yes|ya[ ,]|c\u00f3)"
RAW_ONLY = "^(raw or homecooked food|makanan mentah/dimasak rumah)$"
NONE_ANS = "^(none|no |tidak|tiada)"
PETS_NANO_COND = {
    "Dog parent": "x.dog_flag", "Cat parent": "x.cat_flag",
    "First-time dog parent": "x.dog_flag AND x.ftp", "First-time cat parent": "x.cat_flag AND x.ftp",
    "Dog under 1 year": "x.dog_age_ans AND x.dog_u1", "Dog 1 year and over": "x.dog_age_ans AND NOT x.dog_u1",
    "Cat under 1 year": "x.cat_age_ans AND x.cat_u1", "Cat 1 year and over": "x.cat_age_ans AND NOT x.cat_u1",
    "Dog food brand known": "x.dog_food", "Dog size known": "x.dog_size", "Cat food brand known": "x.cat_food",
    "Pet health concerns": "x.pet_concern",
    "Aged 25 to 45": "x.age_band = 'a2545'", "Working moms": "x.occ_work", "Home-maker": "x.occ_home",
    "Uses a credit card": "x.card_yes",
}
PETS_MICRO_COND = {m: c for ma, m, k, c in MICROS if ma == "Pets"}

def q5(a, b, before=None, only=None):
    """Query 5: moms and data points per country for each Pets (micro, nano) combination (wide: m_n<i> / d_n<i>).
    only = optional list of combination numbers, to test a few quickly."""
    inner = f"""
  IFNULL(b.IND_PET REGEXP '{DOGCAT}', 0) AS p_ind,
  ({ans('b','Dog_Age')} + {ans('b','Dog_Size')} + {ans('b','Dog_FoodBrand')} + {ans('b','cat_age')} + {ans('b','cat_breed')} + {ans('b','cat_food')} > 0) AS p_other,
  (IFNULL(b.IND_PET REGEXP '{DOG_WORDS}', 0) OR {ans('b','Dog_Age')} + {ans('b','Dog_Size')} + {ans('b','Dog_FoodBrand')} > 0) AS dog_flag,
  (IFNULL(b.IND_PET REGEXP '{CAT_WORDS}', 0) OR {ans('b','cat_age')} + {ans('b','cat_breed')} + {ans('b','cat_food')} > 0) AS cat_flag,
  {ans('b','Dog_Age')} AS dog_age_ans, IFNULL(b.Dog_Age REGEXP '{PET_UNDER_1}', 0) AS dog_u1,
  {ans('b','cat_age')} AS cat_age_ans, IFNULL(b.cat_age REGEXP '{PET_UNDER_1}', 0) AS cat_u1,
  IFNULL(LOWER(TRIM(b.first_time_pet)) IN {FIRST_TIME_YES}, 0) AS ftp,
  IFNULL(b.Dog_FoodBrand REGEXP '[^[:space:]]' AND NOT (TRIM(b.Dog_FoodBrand) REGEXP '{RAW_ONLY}'), 0) AS dog_food,
  {ans('b','Dog_Size')} AS dog_size,
  IFNULL(b.cat_food REGEXP '[^[:space:]]' AND NOT (TRIM(b.cat_food) REGEXP '{RAW_ONLY}'), 0) AS cat_food,
  IFNULL(b.pet_concern REGEXP '[^[:space:]]' AND NOT (TRIM(b.pet_concern) REGEXP '{NONE_ANS}'), 0) AS pet_concern,
  IFNULL(c.Occupation REGEXP '{OCC_HOME}', 0) AS occ_home, IFNULL(c.Occupation REGEXP '{OCC_WORK}', 0) AS occ_work,
  IFNULL(TRIM(b.CreditCard) REGEXP '{CARD_YES}', 0) AS card_yes,
  CASE WHEN c.MomDOB > '1940-12-31' AND c.MomDOB <= DATE_SUB(CURDATE(), INTERVAL 13 YEAR) THEN
         CASE WHEN c.MomDOB > DATE_SUB(CURDATE(), INTERVAL 18 YEAR) THEN 'u18' WHEN c.MomDOB > DATE_SUB(CURDATE(), INTERVAL 25 YEAR) THEN 'a1825'
              WHEN c.MomDOB > DATE_SUB(CURDATE(), INTERVAL 45 YEAR) THEN 'a2545' ELSE 'a45' END
       WHEN c.MomAge REGEXP '^(18|19|20|21|22|23|24)' THEN 'a1825'
       WHEN c.MomAge REGEXP '^(2[5-9]|3[0-9]|4[0-5])' THEN 'a2545'
       WHEN c.MomAge REGEXP '^(above|diatas|lebih|4[6-9]|5[0-9])' THEN 'a45' END AS age_band"""
    idx = [i for i in range(len(PETS_COMBOS)) if only is None or i in only]
    def cond(i):
        micro, group, nano = PETS_COMBOS[i]
        return f"({PETS_MICRO_COND[micro]}) AND ({PETS_NANO_COND[nano]})"
    sums = ",\n ".join(f"SUM(x.canon * IFNULL(({cond(i)}), 0)) AS m_n{i}, SUM(IFNULL(({cond(i)}), 0) * x.dp) AS d_n{i}" for i in idx)
    return f"""SELECT {COUNTRY} AS country,
 {sums}
FROM (
 SELECT l.id, l.Country, {CANON} AS canon, {DP} AS dp,{inner}
{FROM_WHERE(a, b, before)}
) x GROUP BY 1 ORDER BY 1"""

def nanos_to_rows(res, macro="Pets", combos=None):
    """Turn the wide Query 5 result (one row per country) into rows for audience_tracker.upsert_db."""
    combos = combos or PETS_COMBOS; out = []
    for _, r in res.iterrows():
        for i, (micro, group, nano) in enumerate(combos):
            if f"m_n{i}" not in res.columns: continue
            for metric, col in (("moms_on_file", f"m_n{i}"), ("data_points", f"d_n{i}")):
                out.append(dict(tab="nano", country=r["country"], macro=macro, micro=micro, group=group, nano=nano, metric=metric, value=int(r[col])))
    return out

def q3_to_totals_and_macros(res):
    """Query 3 already contains the Query 1 totals (women_all) and the Query 2 macros (kids_all, pets_all, women_all).
    Returns rows for the 'totals' and 'macro' tabs, so one Query 3 pass is enough. Senior & health (caregivers) is not included."""
    out = []
    for _, r in res.iterrows():
        c = r["country"]
        out += [dict(tab="totals", country=c, metric="unique_moms", value=int(r["m_women_all"])),
                dict(tab="totals", country=c, metric="data_points", value=int(r["d_women_all"]))]
        for macro, k in (("Kids", "kids_all"), ("Pets", "pets_all"), ("Women", "women_all")):
            out += [dict(tab="macro", country=c, macro=macro, metric="moms_on_file", value=int(r[f"m_{k}"])),
                    dict(tab="macro", country=c, macro=macro, metric="data_points", value=int(r[f"d_{k}"]))]
    return out
