SELECT count(*)
FROM aka_title, cast_info, company_name, keyword, movie_companies, movie_keyword, name, person_info, title
WHERE cast_info.nr_order = 7
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.person_id = name.id;
