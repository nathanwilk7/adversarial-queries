SELECT count(*)
FROM aka_title, cast_info, company_name, complete_cast, keyword, kind_type, movie_companies, movie_info, movie_keyword, role_type, title
WHERE aka_title.season_nr = 1
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND title.kind_id = kind_type.id;
