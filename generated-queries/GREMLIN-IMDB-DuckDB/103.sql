SELECT count(*)
FROM aka_title, cast_info, company_name, keyword, kind_type, movie_companies, movie_keyword, name, title
WHERE aka_title.production_year > 1888
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND title.kind_id = kind_type.id;
