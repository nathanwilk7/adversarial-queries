SELECT count(*)
FROM aka_title, cast_info, movie_companies, movie_info, movie_keyword, movie_link, name, title
WHERE aka_title.season_nr = 1
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
